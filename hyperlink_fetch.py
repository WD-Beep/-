"""可选：抓取工作簿超链接中的 http(s) 页面正文，摘要后并入结构说明（供模型引用）。

默认关闭，避免外网依赖与 SSRF 风险。环境变量：

- QUOTE_FETCH_HYPERLINKS：1/true/on/yes 开启；否则不请求外网。
- QUOTE_FETCH_HYPERLINK_MAX：最多抓取不同 URL 数，默认 5。
- QUOTE_FETCH_HYPERLINK_TIMEOUT：秒，默认 12。
- QUOTE_FETCH_HYPERLINK_MAX_BYTES：单页响应体上限，默认 400_000。
- QUOTE_FETCH_HYPERLINK_TEXT_CHARS：每页摘要最大字符，默认 6000。
- QUOTE_FETCH_HYPERLINK_ALLOWLIST：可选，逗号分隔主机后缀或完整主机；
  非空时仅允许匹配项（如 ``aliyuncs.com,github.com``）。未配置则仅做私网/回环拦截。

不保证 JS 渲染页、登录墙、反爬站可抓；失败时静默跳过，不影响原有仅列 URL 的行为。
"""

from __future__ import annotations

import ipaddress
import os
import re
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from xlsx_rich_context import SheetHyperlink


def _truthy_fetch() -> bool:
    raw = os.environ.get("QUOTE_FETCH_HYPERLINKS", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _int_env(key: str, default: int, *, lo: int, hi: int) -> int:
    v = os.environ.get(key, "").strip()
    if not v.isdigit():
        return default
    return max(lo, min(hi, int(v)))


def _allowlist_hosts() -> list[str]:
    raw = os.environ.get("QUOTE_FETCH_HYPERLINK_ALLOWLIST", "").strip()
    if not raw:
        return []
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def _host_passes_allowlist(host: str, rules: list[str]) -> bool:
    if not rules:
        return True
    h = host.lower().strip(".")
    for rule in rules:
        r = rule.strip().lower().strip(".")
        if not r:
            continue
        if h == r or h.endswith("." + r):
            return True
    return False


def _url_host_safe_for_ssrf(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass
    return True


def _html_to_text(raw: bytes, max_chars: int) -> str:
    try:
        blob = raw.decode("utf-8", errors="replace")
    except Exception:
        return ""
    blob = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", blob)
    blob = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", blob)
    blob = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", blob)
    blob = re.sub(r"<[^>]+>", " ", blob)
    blob = re.sub(r"\s+", " ", blob).strip()
    if len(blob) > max_chars:
        blob = blob[: max_chars - 1] + "…"
    return blob


def fetch_url_text_excerpt(url: str) -> str | None:
    if not _url_host_safe_for_ssrf(url):
        return None
    rules = _allowlist_hosts()
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    if not _host_passes_allowlist(host, rules):
        return None

    timeout = float(_int_env("QUOTE_FETCH_HYPERLINK_TIMEOUT", 12, lo=2, hi=60))
    max_body = _int_env("QUOTE_FETCH_HYPERLINK_MAX_BYTES", 400_000, lo=20_000, hi=2_000_000)
    max_text = _int_env("QUOTE_FETCH_HYPERLINK_TEXT_CHARS", 6000, lo=500, hi=50_000)

    req = Request(
        url,
        headers={
            "User-Agent": "QuoteWorkbench/1.0 (+structure-enrich; contact local admin)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            ctype = str(resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            blob = resp.read(max_body + 1)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return None

    if len(blob) > max_body:
        return None

    if "html" in ctype or not ctype or ctype == "application/octet-stream":
        out = _html_to_text(blob, max_text)
    elif ctype.startswith("text/"):
        try:
            out = blob.decode("utf-8", errors="replace").strip()
        except Exception:
            return None
        out = re.sub(r"\s+", " ", out)
        if len(out) > max_text:
            out = out[: max_text - 1] + "…"
    else:
        return None

    return out if len(out) >= 80 else None


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _excerpt_overlaps_existing(excerpt: str, existing_text: str) -> bool:
    """若摘录长段已与表内结构说明高度重合，跳过以免重复占位。"""
    ex = _collapse_ws(excerpt)
    ba = _collapse_ws(existing_text)
    if len(ex) < 100 or len(ba) < 60:
        return False
    head = ex[: min(480, len(ex))]
    return head in ba


def format_fetched_hyperlink_excerpts(
    links: list[SheetHyperlink],
    *,
    duplicate_against_text: str = "",
) -> str:
    if not _truthy_fetch() or not links:
        return ""

    max_n = _int_env("QUOTE_FETCH_HYPERLINK_MAX", 5, lo=1, hi=20)
    seen: set[str] = set()
    ordered: list[tuple[str, str]] = []
    for h in links:
        t = str(h.target or "").strip()
        if not t.startswith(("http://", "https://")):
            continue
        if t in seen:
            continue
        seen.add(t)
        label = f"{h.sheet_name}!{h.cell_ref}"
        if h.display:
            label += f"（{h.display}）"
        ordered.append((t, label))
        if len(ordered) >= max_n:
            break

    if not ordered:
        return ""

    dup_src = duplicate_against_text or ""
    blocks: list[str] = []
    for url, label in ordered:
        excerpt = fetch_url_text_excerpt(url)
        if not excerpt:
            continue
        if dup_src and _excerpt_overlaps_existing(excerpt, dup_src):
            continue
        blocks.append(f"### {label}\nURL: {url}\n{excerpt}")

    if not blocks:
        return ""

    return (
        "\n\n【以下外链页面正文摘要（自动抓取，仅作结构/规格参考；与表内重复处以表为准）】\n"
        + "\n\n---\n\n".join(blocks)
    )
