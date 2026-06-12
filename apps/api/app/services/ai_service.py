import json
import logging
import random
import re
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.models.influencer import Influencer
from app.services.business_quality import assess_creator_quality

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "beauty": "美妆护肤",
    "tech": "科技数码",
    "gaming": "游戏电竞",
    "fitness": "健身运动",
    "food": "美食探店",
    "travel": "户外旅行",
    "fashion": "时尚穿搭",
    "education": "知识教育",
}

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "twitter": "X(Twitter)",
}

PRODUCT_ANGLES = {
    "beauty": ["护肤测评", "彩妆教程", "成分科普"],
    "tech": ["开箱评测", "对比测评", "效率工具推荐"],
    "gaming": ["游戏实况", "设备评测", "新游体验"],
    "fitness": ["训练计划", "装备测评", "饮食分享"],
    "food": ["探店 Vlog", "食谱教程", "厨房好物"],
    "travel": ["旅行 Vlog", "通勤装备", "城市攻略"],
    "fashion": ["穿搭分享", "单品测评", "季节搭配"],
    "education": ["干货教程", "工具推荐", "学习方法论"],
}


@dataclass
class AnalysisOutput:
    ai_summary: str
    ai_collaboration_suggestion: str
    ai_outreach_message: str
    tags: list[str]
    risk_level: str
    score_reason: str
    source: str
    error_message: str | None = None
    product_fit: float | None = None
    travel_fit_score: float | None = None
    purchasing_power_score: float | None = None
    sales_potential_score: float | None = None
    audience_match_score: float | None = None
    roi_forecast: float | None = None


def _followers_tier(count: int | None) -> str:
    if not count:
        return "粉丝规模待观察"
    if count >= 1_000_000:
        return "粉丝规模较大"
    if count >= 100_000:
        return "粉丝规模中等偏上"
    if count >= 10_000:
        return "粉丝规模中等"
    return "粉丝规模偏小但精准"


def _engagement_tier(rate: float | None) -> str:
    if not rate:
        return "互动数据一般"
    if rate >= 5:
        return "互动率表现优秀"
    if rate >= 2:
        return "互动率较好"
    if rate >= 1:
        return "互动率处于平均水平"
    return "互动率偏低"


def _derive_risk_level(influencer: Influencer) -> str:
    score = influencer.score or 0
    if score >= 75:
        return "low"
    if score >= 50:
        return "medium"
    return "high"


def _clamp_score(value: float | int | None, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return round(max(0.0, min(100.0, score)), 1)


def _coerce_roi(value: object, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return round(max(0.0, float(value)), 1)
    except (TypeError, ValueError):
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            if match:
                return round(max(0.0, float(match.group(0))), 1)
        return default


def _derive_metric_scores(influencer: Influencer) -> dict[str, float | None]:
    quality = assess_creator_quality(influencer)
    score = influencer.score or 0
    engagement = influencer.engagement_rate or 0
    followers = influencer.followers_count or 0
    contact_bonus = 8 if influencer.email or influencer.final_email else 0
    commerce_bonus = 8 if influencer.has_brand_collaboration else 0
    category = (influencer.category or "").lower()

    follower_signal = 35
    if followers >= 1_000_000:
        follower_signal = 92
    elif followers >= 100_000:
        follower_signal = 78
    elif followers >= 10_000:
        follower_signal = 58

    engagement_signal = min(95, 42 + engagement * 8)
    product_fit = _clamp_score(influencer.product_fit, _clamp_score(48 + score * 0.35 + contact_bonus + commerce_bonus))
    sales = _clamp_score(
        influencer.sales_potential_score,
        _clamp_score(35 + engagement_signal * 0.35 + follower_signal * 0.22 + contact_bonus + commerce_bonus),
    )

    return {
        "product_fit": _clamp_score(influencer.product_fit, quality.product_fit if quality.product_fit else product_fit),
        "travel_fit_score": _clamp_score(
            influencer.travel_fit_score,
            86.0 if category == "travel" else _clamp_score(52 + (12 if category in {"fitness", "fashion"} else 0)),
        ),
        "purchasing_power_score": _clamp_score(
            influencer.purchasing_power_score,
            _clamp_score(42 + follower_signal * 0.38 + (8 if category in {"beauty", "fashion", "tech"} else 0)),
        ),
        "sales_potential_score": sales,
        "audience_match_score": _clamp_score(
            influencer.audience_match_score,
            quality.audience_match_score
            if quality.audience_match_score
            else _clamp_score(58 + score * 0.28 + (10 if category in {"beauty", "fashion", "fitness", "travel"} else 0)),
        ),
        "roi_forecast": quality.roi_forecast
        if quality.roi_forecast
        else round(max(1.0, ((sales or score or 50) / 32) + engagement / 10), 1),
    }


def mock_analyze(influencer: Influencer) -> AnalysisOutput:
    category = (influencer.category or "lifestyle").lower()
    category_label = CATEGORY_LABELS.get(category, category)
    platform_label = PLATFORM_LABELS.get(influencer.platform.lower(), influencer.platform)
    display = influencer.display_name or influencer.username

    followers_text = _followers_tier(influencer.followers_count)
    engagement_text = _engagement_tier(influencer.engagement_rate)
    angles = PRODUCT_ANGLES.get(category, ["内容测评", "场景种草"])
    angle = random.choice(angles)
    sub_angle = random.choice(angles)

    email_hint = "已留商务邮箱，触达成本较低" if influencer.email else "暂无公开邮箱，需通过平台私信触达"

    ai_summary = (
        f"该红人主要在{platform_label}发布{category_label}相关内容，{followers_text}，"
        f"{engagement_text}，内容风格偏向{angle}。"
        f"{email_hint}，适合测试{category_label}或相关场景品类合作。"
    )

    collab_formats = {
        "beauty": "建议先以样品测评或 GRWM 短视频合作切入，重点突出功效、肤感与真实使用体验。",
        "tech": "建议先以开箱测评或 60 秒功能演示切入，重点突出核心卖点、对比优势和使用场景。",
        "gaming": "建议以直播试玩或短视频集锦合作，重点突出游戏体验、设备性能与受众匹配度。",
        "fitness": "建议以训练挑战或装备实测合作，重点突出功能性、舒适度和日常训练场景。",
        "food": "建议以探店 Vlog 或食谱共创合作，重点突出产品融入自然场景与真实体验。",
        "travel": "建议先以样品测评或短视频合作切入，重点突出防泼水、容量和通勤场景。",
        "fashion": "建议以穿搭合集或 OOTD 合作，重点突出设计细节、搭配场景和品牌调性。",
        "education": "建议以干货教程或工具清单合作，重点突出实用价值、转化路径和受众匹配。",
    }
    ai_collaboration_suggestion = collab_formats.get(
        category,
        f"建议先以{angle}形式试水合作，重点突出产品核心卖点与{sub_angle}场景。",
    )

    base_tags = influencer.tags or []
    generated_tags = list(dict.fromkeys(base_tags + [category, influencer.platform, angle.replace(" ", "")]))
    tags = generated_tags[:6]

    score_reason = (
        f"内容方向与{category_label}品类匹配度较高；"
        f"{followers_text}；{engagement_text}；"
        f"{'具备商务联系方式' if influencer.email else '缺少邮箱增加触达难度'}。"
    )

    risk_level = _derive_risk_level(influencer)
    metrics = _derive_metric_scores(influencer)

    ai_outreach_message = (
        f"Hi {display}, we've been following your {category_label} content on {platform_label}. "
        f"{followers_text} — we'd love to explore a brand collaboration. Open to a quick chat?"
    )

    return AnalysisOutput(
        ai_summary=ai_summary,
        ai_collaboration_suggestion=ai_collaboration_suggestion,
        ai_outreach_message=ai_outreach_message,
        tags=tags,
        risk_level=risk_level,
        score_reason=score_reason,
        source="mock",
        **metrics,
    )


def _build_llm_prompt(influencer: Influencer) -> str:
    return f"""你是一位海外红人营销分析专家。请根据以下红人数据输出 JSON，不要输出其他内容。

红人数据：
- 平台: {influencer.platform}
- 用户名: {influencer.username}
- 昵称: {influencer.display_name}
- 国家: {influencer.country}
- 语言: {influencer.language}
- 类目: {influencer.category}
- 简介: {influencer.bio}
- 粉丝数: {influencer.followers_count}
- 平均观看: {influencer.avg_views}
- 平均点赞: {influencer.avg_likes}
- 平均评论: {influencer.avg_comments}
- 互动率: {influencer.engagement_rate}
- 邮箱: {influencer.email}
- 优先级: {influencer.final_priority}
- 互动分: {influencer.engagement_score}
- 内容匹配分: {influencer.content_match_score}
- 可联系分: {influencer.contactability_score}
- 商业信号分: {influencer.commercial_signal_score}
- 活跃度分: {influencer.activity_score}
- 风险分: {influencer.risk_score}
- 综合分: {influencer.score}
- 现有标签: {influencer.tags}

请返回 JSON 对象，字段如下：
{{
  "ai_summary": "100-200字中文画像，说明内容方向、粉丝规模、互动表现、合作适配性",
  "ai_collaboration_suggestion": "80-150字中文合作建议，包含合作形式与重点卖点",
  "ai_outreach_message": "80-120字英文或中文触达开场话术，可直接用于邮件/DM",
  "tags": ["标签1", "标签2", "标签3"],
  "risk_level": "low|medium|high",
  "score_reason": "80字以内评分与风险原因",
  "product_fit": 0-100数字,
  "travel_fit_score": 0-100数字,
  "purchasing_power_score": 0-100数字,
  "sales_potential_score": 0-100数字,
  "audience_match_score": 0-100数字,
  "roi_forecast": 例如 1.0 到 5.0 的数字
}}"""


def _parse_llm_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


async def real_llm_analyze(influencer: Influencer) -> AnalysisOutput:
    """
    调用 Kimi (Moonshot) 真实 LLM 分析。

    生产环境可替换为 OpenAI / Claude 等 Provider，保持返回 AnalysisOutput 结构即可。
    """
    if not settings.is_kimi_configured:
        raise ValueError("Kimi API key not configured")

    headers = {
        "Authorization": f"Bearer {settings.kimi_api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.kimi_model,
        "messages": [
            {"role": "system", "content": "你是海外红人营销分析助手，仅返回合法 JSON。"},
            {"role": "user", "content": _build_llm_prompt(influencer)},
        ],
        # kimi-k2.5 仅允许 temperature=0.6，其它值会 400
        "temperature": 0.6,
        "max_tokens": 8192,
        "thinking": {"type": "disabled"},
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            f"{settings.kimi_api_base.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = (exc.response.text or "")[:500]
            raise RuntimeError(f"Kimi API HTTP {exc.response.status_code}: {body}") from exc
        data = response.json()

    message = data["choices"][0]["message"]
    content = (message.get("content") or message.get("reasoning_content") or "").strip()
    if not content:
        raise ValueError("Kimi 返回空内容（content 与 reasoning_content 均为空）")
    parsed = _parse_llm_json(content)
    fallback_metrics = _derive_metric_scores(influencer)

    return AnalysisOutput(
        ai_summary=str(parsed["ai_summary"]),
        ai_collaboration_suggestion=str(parsed["ai_collaboration_suggestion"]),
        ai_outreach_message=str(parsed.get("ai_outreach_message", "")),
        tags=[str(tag) for tag in parsed.get("tags", [])][:8],
        risk_level=str(parsed.get("risk_level", _derive_risk_level(influencer))),
        score_reason=str(parsed.get("score_reason", "")),
        source="kimi",
        product_fit=_clamp_score(parsed.get("product_fit"), fallback_metrics["product_fit"]),
        travel_fit_score=_clamp_score(parsed.get("travel_fit_score"), fallback_metrics["travel_fit_score"]),
        purchasing_power_score=_clamp_score(
            parsed.get("purchasing_power_score"),
            fallback_metrics["purchasing_power_score"],
        ),
        sales_potential_score=_clamp_score(
            parsed.get("sales_potential_score"),
            fallback_metrics["sales_potential_score"],
        ),
        audience_match_score=_clamp_score(
            parsed.get("audience_match_score"),
            fallback_metrics["audience_match_score"],
        ),
        roi_forecast=_coerce_roi(parsed.get("roi_forecast"), fallback_metrics["roi_forecast"]),
    )


def heuristic_analyze(
    influencer: Influencer,
    *,
    reason: str = "no_api_key",
    error: str | None = None,
) -> AnalysisOutput:
    """仅根据已采集字段计算评分，不生成模拟文案。"""
    metrics = _derive_metric_scores(influencer)
    quality = assess_creator_quality(influencer)
    risk_level = _derive_risk_level(influencer)
    if reason == "kimi_failed" and error:
        score_reason = f"AI 分析失败：{error}。已降级为本地规则评分：{quality.reason_text}"
        source = "heuristic_fallback"
    elif reason == "no_api_key":
        score_reason = f"未配置 KIMI_API_KEY，已使用本地规则评分：{quality.reason_text}"
        source = "heuristic"
    else:
        score_reason = f"已使用本地规则评分：{quality.reason_text}"
        source = "heuristic"
    return AnalysisOutput(
        ai_summary="",
        ai_collaboration_suggestion="",
        ai_outreach_message="",
        tags=influencer.tags or [],
        risk_level=risk_level,
        score_reason=score_reason,
        source=source,
        error_message=error,
        **metrics,
    )


async def analyze_influencer(influencer: Influencer) -> AnalysisOutput:
    """统一分析入口：优先 Kimi；失败或未配置时使用指标启发式，不使用 mock 假数据。"""
    if not settings.is_kimi_configured:
        return heuristic_analyze(influencer, reason="no_api_key")
    try:
        return await real_llm_analyze(influencer)
    except Exception as exc:
        err_text = str(exc).strip() or exc.__class__.__name__
        logger.warning("Kimi analyze failed for @%s, fallback to heuristic: %s", influencer.username, err_text)
        return heuristic_analyze(influencer, reason="kimi_failed", error=err_text)
