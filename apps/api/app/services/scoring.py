# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：scoring
from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"


def _followers_score(followers: int | None) -> float:
    if not followers or followers <= 0:
        return 0.0
    if followers >= 1_000_000:
        return 100.0
    if followers >= 500_000:
        return 90.0
    if followers >= 100_000:
        return 80.0
    if followers >= 50_000:
        return 70.0
    if followers >= 10_000:
        return 55.0
    if followers >= 5_000:
        return 40.0
    return 25.0


def _engagement_score(rate: float | None) -> float:
    if not rate or rate <= 0:
        return 0.0
    if rate >= 8.0:
        return 100.0
    if rate >= 5.0:
        return 85.0
    if rate >= 3.0:
        return 70.0
    if rate >= 1.5:
        return 50.0
    if rate >= 0.5:
        return 30.0
    return 15.0


def _category_score(influencer_category: str | None, task: CollectionTask | None) -> float:
    if not task or not task.category:
        return 75.0
    if not influencer_category:
        return 40.0
    if influencer_category.lower() == task.category.lower():
        return 100.0
    return 35.0


def _email_score(email: str | None) -> float:
    return 100.0 if email else 0.0


def _locale_score(country: str | None, language: str | None, task: CollectionTask | None) -> float:
    if not task or not task.country:
        return 80.0
    if country and country.upper() == task.country.upper():
        return 100.0
    english_markets = {"US", "UK", "CA", "AU", "IE", "NZ"}
    if (
        task.country.upper() in english_markets
        and country
        and country.upper() in english_markets
    ):
        return 60.0
    if language and language.lower() == "en" and task.country.upper() in english_markets:
        return 50.0
    return 20.0


def calculate_score(data: CollectedInfluencer, task: CollectionTask | None = None) -> float:
    """综合评分 0-100。"""
    category = _category_score(data.category, task) * 0.30
    followers = _followers_score(data.followers_count) * 0.20
    engagement = _engagement_score(data.engagement_rate) * 0.25
    email = _email_score(data.email) * 0.15
    locale = _locale_score(data.country, data.language, task) * 0.10
    return round(category + followers + engagement + email + locale, 1)


def calculate_risk_level(score: float) -> str:
    if score >= 75:
        return RISK_LOW
    if score >= 50:
        return RISK_MEDIUM
    return RISK_HIGH


def calculate_composite_score_from_metrics(
    *,
    product_fit: float | None = None,
    travel_fit_score: float | None = None,
    purchasing_power_score: float | None = None,
    sales_potential_score: float | None = None,
    audience_match_score: float | None = None,
    engagement_rate: float | None = None,
    email: str | None = None,
) -> float | None:
    """根据 AI/启发式指标合成综合评分 0-100。"""
    metrics = [
        (product_fit, 0.22),
        (travel_fit_score, 0.18),
        (purchasing_power_score, 0.15),
        (sales_potential_score, 0.18),
        (audience_match_score, 0.17),
        (_engagement_score(engagement_rate), 0.10),
    ]
    weighted = 0.0
    total_weight = 0.0
    for value, weight in metrics:
        if value is None:
            continue
        weighted += float(value) * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    score = weighted / total_weight
    if email:
        score = min(100.0, score + 3.0)
    return round(score, 1)


def calculate_influencer_composite_score(influencer) -> float | None:
    """从已持久化的红人字段计算综合评分。"""
    return calculate_composite_score_from_metrics(
        product_fit=influencer.product_fit,
        travel_fit_score=influencer.travel_fit_score,
        purchasing_power_score=influencer.purchasing_power_score,
        sales_potential_score=influencer.sales_potential_score,
        audience_match_score=influencer.audience_match_score,
        engagement_rate=influencer.engagement_rate,
        email=influencer.final_email or influencer.email,
    )
