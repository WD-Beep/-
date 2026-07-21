# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：default message templates
"""产品级系统默认话术模板（首次访问话术库或 AI 生成兜底时使用）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.tenant import TenantContext
from app.models.message_template import MessageTemplate

SYSTEM_DEFAULT_TAG = "system_default"


@dataclass(frozen=True)
class DefaultMessageTemplateSpec:
    title: str
    scenario: str
    language: str
    tags: tuple[str, ...]
    content: str
    note: str = ""


SYSTEM_DEFAULT_TEMPLATE_SPECS: tuple[DefaultMessageTemplateSpec, ...] = (
    DefaultMessageTemplateSpec(
        title="First Collaboration Outreach",
        scenario="first_contact",
        language="en",
        tags=("outreach", "first_contact"),
        content=(
            "Hi {name},\n\n"
            "I'm reaching out from {brand} because your {platform} content around {category} "
            "feels like a strong fit for what we do.\n\n"
            "We would love to explore a simple collaboration — for example a short post, Reel, "
            "or story that shows how our product fits naturally into your audience's routine.\n\n"
            "If you are open to it, I'd be happy to share a brief overview and hear what formats "
            "work best for you.\n\n"
            "Best regards,\n{brand} Team"
        ),
        note="系统默认：首次合作邀约",
    ),
    DefaultMessageTemplateSpec(
        title="Follow-up After No Reply",
        scenario="follow_up_no_reply",
        language="en",
        tags=("outreach", "follow_up"),
        content=(
            "Hi {name},\n\n"
            "Just following up on my earlier note about a potential collaboration with {brand}. "
            "No rush at all — I wanted to check whether partnership emails are the best channel "
            "for you, or if another contact method works better.\n\n"
            "Happy to send a short summary if helpful.\n\n"
            "Best,\n{brand} Team"
        ),
        note="系统默认：跟进未回复",
    ),
    DefaultMessageTemplateSpec(
        title="Product Introduction & Collaboration Angle",
        scenario="custom",
        language="en",
        tags=("outreach", "product_intro"),
        content=(
            "Hi {name},\n\n"
            "I'm with {brand}. We focus on {product} and thought your content style could be a "
            "natural fit for a lightweight creator partnership.\n\n"
            "We are not looking for a hard sell — more a genuine fit check: whether our product "
            "could be useful to your audience in a way that still feels authentic to your voice.\n\n"
            "Would you be open to a quick chat about a simple content idea?\n\n"
            "Best regards,\n{brand} Team"
        ),
        note="系统默认：产品介绍/合作切入",
    ),
    DefaultMessageTemplateSpec(
        title="Premium Creator Invitation",
        scenario="first_contact",
        language="en",
        tags=("outreach", "premium", "high_value"),
        content=(
            "Hi {name},\n\n"
            "I'm reaching out from {brand}. We have been impressed by the quality and consistency "
            "of your {platform} presence, especially how thoughtfully you present {category} content "
            "to your audience.\n\n"
            "We are exploring a small number of creator partnerships this quarter and would value "
            "your perspective on whether a collaboration could make sense.\n\n"
            "If interested, I can share a concise brief and learn what partnership formats you "
            "prefer.\n\n"
            "Warm regards,\n{brand} Team"
        ),
        note="系统默认：高价值红人专属邀约",
    ),
    DefaultMessageTemplateSpec(
        title="Second Gentle Touch",
        scenario="follow_up_no_reply",
        language="en",
        tags=("outreach", "second_touch"),
        content=(
            "Hi {name},\n\n"
            "Circling back once more in case my earlier message got buried. We would still love "
            "to explore a low-pressure collaboration with {brand} if the timing is better now.\n\n"
            "If now is not a fit, no worries at all — a quick note either way would be appreciated.\n\n"
            "Thank you,\n{brand} Team"
        ),
        note="系统默认：二次触达",
    ),
    DefaultMessageTemplateSpec(
        title="Polite Decline / Not Now",
        scenario="reject",
        language="en",
        tags=("outreach", "decline"),
        content=(
            "Hi {name},\n\n"
            "Thank you again for your time and for considering a collaboration with {brand}. "
            "After reviewing fit and timing, we will pass for now, but we genuinely appreciate "
            "your work and the conversation.\n\n"
            "We would be glad to stay in touch for a future opportunity if things change on either side.\n\n"
            "Best wishes,\n{brand} Team"
        ),
        note="系统默认：暂缓/礼貌拒绝",
    ),
)


def is_system_default_template(row: MessageTemplate) -> bool:
    tags = {str(tag).strip().lower() for tag in (row.tags or []) if str(tag).strip()}
    return SYSTEM_DEFAULT_TAG in tags


def format_template_source_title(title: str, *, from_system_default: bool) -> str:
    text = (title or "").strip()
    if not text:
        return "系统默认话术" if from_system_default else ""
    if from_system_default and not text.startswith("系统默认"):
        return f"系统默认话术 · {text}"
    return text


async def count_product_templates(db: AsyncSession, *, product_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(MessageTemplate).where(
                MessageTemplate.product_id == product_id
            )
        )
        or 0
    )


async def ensure_default_templates_for_product(
    db: AsyncSession,
    *,
    ctx: TenantContext,
    product_id: int,
) -> int:
    """若当前产品无话术，写入系统默认模板（绑定 product/workspace）。"""
    if await count_product_templates(db, product_id=product_id) > 0:
        return 0

    created = 0
    for spec in SYSTEM_DEFAULT_TEMPLATE_SPECS:
        tags = list(dict.fromkeys([*spec.tags, SYSTEM_DEFAULT_TAG, "outreach"]))
        row = MessageTemplate(
            user_id=ctx.user_id,
            workspace_id=ctx.workspace_id,
            product_id=product_id,
            title=spec.title,
            scenario=spec.scenario,
            platform=None,
            language=spec.language,
            tags=tags,
            content=spec.content,
            note=spec.note,
        )
        db.add(row)
        created += 1
    if created:
        await db.commit()
    return created


def build_fallback_template_objects() -> list[MessageTemplate]:
    """内存兜底（未 seed 到 DB 时供 AI 参考）。"""
    rows: list[MessageTemplate] = []
    for idx, spec in enumerate(SYSTEM_DEFAULT_TEMPLATE_SPECS, start=1):
        rows.append(
            MessageTemplate(
                id=-idx,
                user_id=0,
                workspace_id=0,
                product_id=0,
                title=spec.title,
                scenario=spec.scenario,
                platform=None,
                language=spec.language,
                tags=[*spec.tags, SYSTEM_DEFAULT_TAG],
                content=spec.content,
                note=spec.note,
            )
        )
    return rows
