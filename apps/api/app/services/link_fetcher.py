from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx


MAX_CLEAN_TEXT_LENGTH = 30_000
MIN_CLEAN_TEXT_LENGTH = 80


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "header", "svg", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attr_map = {str(k).lower(): str(v) for k, v in attrs if k and v}
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.description = attr_map.get("content", self.description)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "header", "svg", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
            return
        if self._skip_depth == 0:
            self._text_parts.append(text)

    def result(self) -> tuple[str, str]:
        self.title = " ".join(self._title_parts).strip()
        body = "\n".join(self._text_parts)
        if self.description:
            body = f"{self.description}\n{body}"
        clean = re.sub(r"\n{3,}", "\n\n", body).strip()
        return self.title, clean[:MAX_CLEAN_TEXT_LENGTH]


def detect_source_type(url: str, clean_text: str = "") -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "amazon." in host:
        return "amazon"
    if "myshopify.com" in host or "cdn.shopify.com" in clean_text.lower():
        return "shopify"
    if any(token in path for token in ("/products/", "/product/", "/p/", "/dp/")):
        return "product_page"
    if parsed.scheme and host:
        return "website"
    return "unknown"


async def fetch_url_content(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid URL")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    raw_html = response.text
    parser = _ReadableHTMLParser()
    parser.feed(raw_html)
    title, clean_text = parser.result()
    if len(clean_text) < MIN_CLEAN_TEXT_LENGTH:
        raise ValueError("Fetched page text is too short to parse useful knowledge")
    return {
        "url": str(response.url),
        "domain": urlparse(str(response.url)).netloc.lower(),
        "source_type": detect_source_type(str(response.url), raw_html),
        "raw_html": raw_html,
        "clean_text": clean_text,
        "title": title,
    }
