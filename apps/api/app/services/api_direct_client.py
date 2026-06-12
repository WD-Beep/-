"""API Direct (apidirect.io) HTTP 客户端。"""



from __future__ import annotations



import logging

from contextvars import ContextVar



import httpx



from app.core.config import settings

from app.services.http_retry import execute_with_retry



logger = logging.getLogger(__name__)



API_DIRECT_BASE_DEFAULT = "https://apidirect.io"



_request_counts: ContextVar[dict[str, int]] = ContextVar("api_direct_request_counts", default={})





class ApiDirectError(Exception):

    """API Direct 调用失败。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_rate_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, ApiDirectError) and exc.status_code == 429:
        return True
    text = str(exc)
    return "(429)" in text or "429" in text





class ApiDirectBudgetExceeded(ApiDirectError):

    """单任务单平台 API 请求次数已达上限。"""





def reset_request_budget() -> None:

    _request_counts.set({})





def get_request_counts() -> dict[str, int]:

    return dict(_request_counts.get({}))





def get_request_count(platform: str | None = None) -> int:

    counts = _request_counts.get({})

    if platform:

        return counts.get(platform, 0)

    return sum(counts.values())





def _record_request(platform: str | None) -> None:

    if not platform:

        return

    counts = dict(_request_counts.get({}))

    counts[platform] = counts.get(platform, 0) + 1

    _request_counts.set(counts)





def _check_budget(platform: str | None) -> None:

    if not platform:

        return

    limit = settings.api_direct_max_requests_per_platform

    if limit <= 0:

        return

    current = get_request_count(platform)

    if current >= limit:

        raise ApiDirectBudgetExceeded(

            f"API Direct {platform} 请求次数已达本任务上限（{limit} 次），已停止继续调用以避免费用暴涨"

        )





def _api_key() -> str:

    return settings.api_direct_api_key.strip()





def _headers() -> dict[str, str]:

    key = _api_key()

    if not key:

        raise ApiDirectError("未配置 API_DIRECT_API_KEY")

    return {"X-API-Key": key, "accept": "application/json"}





def _parse_error(data: dict) -> str:

    for key in ("error", "message", "detail"):

        value = data.get(key)

        if isinstance(value, str) and value.strip():

            return value.strip()

    code = data.get("code")

    if code:

        return str(code)

    return "unknown error"





async def ad_get(path: str, *, params: dict | None = None, platform: str | None = None) -> dict:

    """GET JSON；路径以 / 开头。网络/429/5xx 指数退避重试，400/401/403 不重试。"""

    _check_budget(platform)

    base = (settings.api_direct_api_base or API_DIRECT_BASE_DEFAULT).rstrip("/")

    url = f"{base}{path}"

    timeout = settings.api_direct_request_timeout



    async with httpx.AsyncClient(timeout=timeout) as client:

        response = await execute_with_retry(

            lambda: client.get(url, headers=_headers(), params=params or {}),

            label=f"API Direct {path}",

        )



    _record_request(platform)



    text_preview = response.text[:500]

    try:

        data = response.json()

    except ValueError as exc:

        raise ApiDirectError(

            f"API Direct 返回非 JSON ({response.status_code}): {text_preview}"

        ) from exc



    if not isinstance(data, dict):

        raise ApiDirectError(f"API Direct 响应格式异常 ({response.status_code})")



    if response.status_code == 402:

        raise ApiDirectError("API Direct 余额不足，请在 apidirect.io 充值后重试。")



    if response.status_code == 401:

        raise ApiDirectError("API Direct API 密钥无效（401）")



    if response.status_code == 403 and data.get("code") == "account_blocked":

        raise ApiDirectError("API Direct 账户因付款问题被暂停，请更新支付方式。")



    if response.status_code >= 400:

        detail = _parse_error(data) if data else text_preview

        raise ApiDirectError(
            f"API Direct 请求失败 ({response.status_code}): {detail}",
            status_code=response.status_code,
        )



    if data.get("error"):

        raise ApiDirectError(f"API Direct: {_parse_error(data)}")



    return data

