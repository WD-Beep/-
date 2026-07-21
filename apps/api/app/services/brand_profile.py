# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：brand profile
"""品牌资料卡：第一版从 Product 字段组合，后续可升级为独立 profile 表。"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.link_knowledge_base import LinkKnowledgeBase
from app.models.tenant import Product


@dataclass(frozen=True)
class BrandProfile:
    brand_name: str
    brand_one_liner: str | None = None
    product_summary: str | None = None
    key_selling_points: list[str] = field(default_factory=list)
    target_audience: str | None = None
    collaboration_preferences: str | None = None
    product_links: list[str] = field(default_factory=list)
    allowed_claims: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    tone: str = "professional"
    signature: str | None = None

    def to_prompt_block(self) -> str:
        lines = [f"Brand: {self.brand_name}"]
        if self.brand_one_liner:
            lines.append(f"One-liner: {self.brand_one_liner}")
        if self.product_summary:
            lines.append(f"Product summary: {self.product_summary}")
        if self.key_selling_points:
            lines.append("Key selling points: " + "; ".join(self.key_selling_points))
        if self.target_audience:
            lines.append(f"Target audience: {self.target_audience}")
        if self.collaboration_preferences:
            lines.append(f"Collaboration preferences: {self.collaboration_preferences}")
        if self.product_links:
            lines.append("Product links: " + "; ".join(self.product_links[:3]))
        if self.allowed_claims:
            lines.append("Allowed claims: " + "; ".join(self.allowed_claims))
        if self.forbidden_claims:
            lines.append("Forbidden claims (do NOT mention): " + "; ".join(self.forbidden_claims))
        if self.tone:
            lines.append(f"Preferred tone: {self.tone}")
        if self.signature:
            lines.append(f"Signature: {self.signature}")
        return "\n".join(lines)


DEFAULT_FORBIDDEN_CLAIMS = (
    "Do not promise specific prices, commissions, or free samples unless explicitly in brand/knowledge context.",
    "Do not exaggerate brand capabilities beyond provided materials.",
)

PLACEHOLDER_BRAND_NAMES = {"", "默认品牌", "默认项目", "Brand", "Default Brand", "Default Project"}
ASCII_BRAND_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[ -][A-Z0-9][A-Za-z0-9]*){0,3}\b")
GENERIC_BRAND_WORDS = {"Amazon", "YouTube", "TikTok", "Instagram", "Facebook", "Pinterest", "Shopify"}


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def _clean_ascii_brand(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or _contains_cjk(text):
        return None
    if any(ch.isalpha() for ch in text) and len(text) <= 80:
        return text
    return None


def _extract_ascii_brand_from_text(text: str) -> str | None:
    for match in ASCII_BRAND_RE.finditer(text or ""):
        candidate = match.group(0).strip(" -")
        if candidate in GENERIC_BRAND_WORDS:
            continue
        if len(candidate) >= 3 and any(ch.isalpha() for ch in candidate):
            return candidate
    return None



async def _infer_brand_name_from_knowledge(db: AsyncSession, *, product_id: int) -> str | None:
    link_rows = (
        await db.execute(
            select(
                LinkKnowledgeBase.extracted_knowledge,
                LinkKnowledgeBase.summary,
                LinkKnowledgeBase.clean_text,
                LinkKnowledgeBase.name,
            )
            .where(LinkKnowledgeBase.product_id == product_id)
            .order_by(LinkKnowledgeBase.updated_at.desc(), LinkKnowledgeBase.id.desc())
            .limit(10)
        )
    ).all()
    for extracted, summary, clean_text, name in link_rows:
        if isinstance(extracted, dict):
            for key in ("brand_name", "brand", "company", "store_name"):
                cleaned = _clean_ascii_brand(extracted.get(key))
                if cleaned:
                    return cleaned
        for value in (summary, clean_text, name):
            inferred = _extract_ascii_brand_from_text(str(value or "")[:2000])
            if inferred:
                return inferred

    rows = (
        await db.execute(
            select(KnowledgeDocument.file_name, KnowledgeChunk.content)
            .join(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.product_id == product_id)
            .order_by(KnowledgeDocument.id.asc(), KnowledgeChunk.id.asc())
            .limit(20)
        )
    ).all()
    haystack = "\n".join(f"{name or ''}\n{content or ''}" for name, content in rows)
    if "ScandiHome" in haystack:
        return "ScandiHome"
    inferred = _extract_ascii_brand_from_text(haystack)
    if inferred:
        return inferred
    return None

async def load_brand_profile(db: AsyncSession, *, product_id: int) -> BrandProfile:
    product = await db.get(Product, product_id)
    if not product:
        return BrandProfile(
            brand_name="Brand",
            forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
        )
    brand_name = (product.brand or product.name or "Brand").strip()
    if brand_name in PLACEHOLDER_BRAND_NAMES or _contains_cjk(brand_name):
        brand_name = await _infer_brand_name_from_knowledge(db, product_id=product_id) or "Brand"
    summary = (product.description or "").strip() or None
    product_link_rows = (
        await db.scalars(
            select(LinkKnowledgeBase.url)
            .where(LinkKnowledgeBase.product_id == product_id, LinkKnowledgeBase.is_active.is_(True))
            .order_by(LinkKnowledgeBase.updated_at.desc(), LinkKnowledgeBase.id.desc())
            .limit(3)
        )
    ).all()
    product_links = [url for url in product_link_rows if url]
    return BrandProfile(
        brand_name=brand_name,
        brand_one_liner=summary[:200] if summary else None,
        product_summary=summary,
        product_links=product_links,
        tone="professional",
        signature=f"{brand_name} Team",
        forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
    )
