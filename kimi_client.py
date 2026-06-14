

from __future__ import annotations

import json
import os
import re
import socket
import copy
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from bag_quote_costing import build_llm_system_prompt_addon, detect_bag_product, resolve_bag_quote_skill
from bag_quote_pipeline import build_bag_structure_llm_addon


DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
FALLBACK_BASE_URLS = (
    "https://api.moonshot.ai/v1",
    "https://api.moonshot.cn/v1",
)
DEFAULT_MODEL = "kimi-k2.6"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.3-codex"
# Cloudflare 等网关会拦截 Python-urllib 默认 UA（403 / error code 1010）。
LLM_HTTP_USER_AGENT = "QuoteEngine/1.0 (compatible; curl/8.0)"

_LAST_CALL_STATE: dict[str, Any] = {
    "success": None,
    "error": "",
    "at_ms": 0,
    "endpoint": "",
}

TRANSIENT_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _llm_retry_attempts() -> int:
    raw = os.getenv("LLM_RETRY_ATTEMPTS") or os.getenv("KIMI_RETRY_ATTEMPTS") or "3"
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        parsed = 3
    return max(1, min(parsed, 6))


def _llm_retry_backoff_seconds(attempt_index: int) -> float:
    raw = os.getenv("LLM_RETRY_BACKOFF_SECONDS") or os.getenv("KIMI_RETRY_BACKOFF_SECONDS") or "0.8"
    try:
        base = float(str(raw).strip())
    except (TypeError, ValueError):
        base = 0.8
    base = max(0.0, min(base, 5.0))
    return min(base * (2 ** max(0, attempt_index - 1)), 8.0)


def _split_base_urls(raw: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;\s]+", str(raw or "")):
        text = part.strip()
        if not text:
            continue
        url = normalize_base_url(text)
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _configured_fallback_base_urls(api_key_source: str) -> list[str]:
    provider_envs: tuple[str, ...] = ("OPENAI_FALLBACK_BASE_URLS",) if api_key_source == "OPENAI_API_KEY" else ()

    out: list[str] = []
    seen: set[str] = set()
    for env_name in (*provider_envs, "LLM_FALLBACK_BASE_URLS"):
        for url in _split_base_urls(os.getenv(env_name) or ""):
            if url in seen:
                continue
            seen.add(url)
            out.append(url)
    return out


def _mask_api_key(key: str) -> str:
    text = str(key or "").strip()
    if not text:
        return ""
    if len(text) <= 10:
        return "***"
    return f"{text[:7]}…{text[-4:]}"


def _is_openai_config(config: Any = None, *, api_key_source: str = "") -> bool:
    if config is not None:
        api_key_source = config.api_key_source
    return str(api_key_source or "").strip() == "OPENAI_API_KEY"


def _resolve_provider_name(config: KimiConfig) -> str:
    bu = str(config.base_url or "").lower()
    if "api.openai.com" in bu:
        return "openai"
    return "openai-compatible"


def _classify_http_error(http_code: int, body: str) -> str:
    blob = (body or "").lower()
    if http_code == 400:
        if any(
            token in blob
            for token in (
                "invalid model",
                "model_not_found",
                "does not exist",
                "unknown model",
                "model is not",
                "unsupported model",
            )
        ) or ("model" in blob and "invalid" in blob):
            return "invalid_model"
        return "http_400"
    return f"http_{http_code}"


def _openai_model_error_hint(error_code: str) -> str:
    if error_code == "invalid_model":
        return "请检查 OPENAI_MODEL 是否为当前 API 可用模型（例如 gpt-5.3-codex）。"
    if error_code == "http_400":
        return "OpenAI 接口返回 HTTP 400，请检查请求体与 OPENAI_MODEL。"
    return ""


def _resolve_base_url_for_source(api_key_source: str) -> str:
    return (os.getenv("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL).strip()


def _record_last_call(*, success: bool, error: str = "", endpoint: str = "") -> None:
    import time

    _LAST_CALL_STATE["success"] = success
    _LAST_CALL_STATE["error"] = str(error or "").strip()
    _LAST_CALL_STATE["at_ms"] = int(time.time() * 1000)
    if endpoint:
        _LAST_CALL_STATE["endpoint"] = str(endpoint).strip()


def _endpoint_base_url(endpoint: str) -> str:
    ep = (endpoint or "").rstrip("/")
    if ep.endswith("/chat/completions"):
        return ep[: -len("/chat/completions")]
    return ep


_BILLING_HINT_PATTERN = re.compile(
    r"insufficient|quota|balance|billing|payment\s*required|credit|recharge|expired|"
    r"exceed|limit|usage|扣费|余额|欠费|额度|配额|用尽|充值|套餐|费用不足",
    re.IGNORECASE,
)


def _http_error_body(exc: error.HTTPError) -> str:
    try:
        fp = getattr(exc, "fp", None)
        if fp is not None:
            return fp.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def billing_reminder_from_http(http_code: int, body: str) -> str | None:
    """从 Moonshot/Kimi 等平台 HTTP 错误中提取「余额/额度」类用户提示。"""
    blob = f"{http_code} {(body or '').strip()}"
    if not blob.strip():
        return None
    # 显式计费/欠费类状态码
    if http_code == 402:
        return (
            "提示：模型接口返回与付费/余额相关错误（HTTP 402），请到 Moonshot/Kimi 开放平台核对账户余额或套餐是否可用。"
        )
    if http_code == 429:
        if _BILLING_HINT_PATTERN.search(blob):
            return (
                "提示：可能是调用额度或计费策略触发的限制（HTTP 429），请到控制台查看余额、包月包量或限速说明，稍后再试。"
            )
        return "提示：请求过于频繁（HTTP 429），请稍后再试。"
    if http_code in {401, 403} and _BILLING_HINT_PATTERN.search(blob):
        return (
            "提示：返回内容涉及账户权限、余额或调用额度（HTTP "
            f"{http_code}）。请核对 API Key 是否与平台一致，并检查账户余额/套餐。"
        )
    if http_code >= 500:
        return None
    if _BILLING_HINT_PATTERN.search(blob):
        return (
            "提示：接口返回信息涉及余额、配额或计费，请到 Kimi/Moonshot 控制台检查账户状态、余量与账单后重试。"
        )
    return None


def merge_billing_reminder(
    status: dict[str, Any],
    http_code: int,
    exc: error.HTTPError | None = None,
    *,
    body: str | None = None,
) -> None:
    """将计费类提示写入 status['billing_reminder']（供前端与错误文案使用）。"""
    raw = body if body is not None else (_http_error_body(exc) if exc is not None else "")
    hint = billing_reminder_from_http(http_code, raw)
    if hint:
        status["billing_reminder"] = hint


INVALID_PRICE_TEXTS = {
    "",
    "-",
    "n/a",
    "na",
    "null",
    "none",
    "yes",
    "no",
    "true",
    "false",
    "是",
    "否",
}


def _moonshot_compatible_base(base_url: str) -> bool:
    """Moonshot/Kimi OpenAPI 专有字段（如 thinking）；DeepSeek/OpenAI 兼容服务不传。"""
    u = (base_url or "").lower()
    return "moonshot" in u


def _maybe_thinking_field(base_url: str) -> dict[str, Any]:
    if _moonshot_compatible_base(base_url):
        return {"thinking": {"type": "disabled"}}
    return {}


@dataclass(frozen=True)
class KimiConfig:
    api_key: str
    api_key_source: str
    base_url: str
    model: str
    timeout_s: int
    temperature: float


def get_kimi_config() -> KimiConfig:
    api_key, api_key_source = first_non_empty_env("OPENAI_API_KEY")
    base_url = normalize_base_url(_resolve_base_url_for_source(api_key_source))
    model = (os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()
    timeout_s = _parse_timeout(os.getenv("KIMI_TIMEOUT_SECONDS"), 25)
    temperature = _parse_temperature(os.getenv("KIMI_TEMPERATURE"), 1.0)
    return KimiConfig(
        api_key=api_key,
        api_key_source=api_key_source,
        base_url=base_url,
        model=model,
        timeout_s=timeout_s,
        temperature=temperature,
    )


def _base_llm_status(config: KimiConfig) -> dict[str, Any]:
    candidates = build_endpoint_candidates(
        config.base_url,
        api_key_source=config.api_key_source,
    )
    endpoint = candidates[0] if candidates else config.base_url
    return {
        "provider": _resolve_provider_name(config),
        "model": config.model,
        "base_url": config.base_url,
        "endpoint": endpoint,
        "api_key_source": config.api_key_source,
        "enabled": bool(config.api_key),
        "used": False,
        "error": "",
    }


def _capture_llm_suggested_amount(row: dict[str, Any], ai_row: dict[str, Any]) -> bool:
    """Store model amount for audit only; never write to row['amount']."""
    ai_amount = _parse_float(ai_row.get("amount"))
    if ai_amount is None or ai_amount <= 0:
        return False
    row["llm_suggested_amount"] = round(ai_amount, 2)
    return True


def _finalize_row_amount_local_only(row: dict[str, Any]) -> None:
    """Final row amount must come from local unit_price × usage formula."""
    row.pop("amount_ai", None)
    _backfill_amount_from_unit_price(row)
    _sanitize_row_amount_for_price_usage_mismatch(row)
    row.pop("amount_ai", None)


def get_kimi_status(*, probe: bool = False) -> dict[str, Any]:
    config = get_kimi_config()
    out: dict[str, Any] = dict(_base_llm_status(config))
    out.update(
        {
            "last_call_success": _LAST_CALL_STATE.get("success"),
            "last_call_error": str(_LAST_CALL_STATE.get("error") or ""),
        }
    )
    if probe and config.api_key:
        out.update(probe_llm_connection())
    return out


def probe_llm_connection() -> dict[str, Any]:
    """Lightweight connectivity probe; updates _LAST_CALL_STATE."""
    import time

    config = get_kimi_config()
    if not config.api_key:
        _record_last_call(success=False, error="missing_api_key")
        return {
            "last_call_success": False,
            "last_call_error": "missing_api_key",
            "probe_latency_ms": 0,
        }
    body = {
        "model": config.model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_completion_tokens": 16,
        "temperature": config.temperature,
    }
    body.update(_maybe_thinking_field(config.base_url))
    status: dict[str, Any] = dict(_base_llm_status(config))
    t0 = time.perf_counter()
    raw, st = _call_kimi_with_fallback(body, config, status)
    latency = int((time.perf_counter() - t0) * 1000)
    err = str(st.get("error") or "").strip()
    ok = raw is not None and not err
    _record_last_call(success=ok, error=err if not ok else "")
    out = {
        "last_call_success": ok,
        "last_call_error": err if not ok else "",
        "probe_latency_ms": latency,
        "endpoint": str(_LAST_CALL_STATE.get("endpoint") or "").strip(),
    }
    hint = str(st.get("error_hint") or "").strip()
    if hint:
        out["error_hint"] = hint
    return out


def build_llm_health_report(*, live_probe: bool = True) -> dict[str, Any]:
    """Manual LLM connectivity report (optional live probe; never logs full API key)."""
    config = get_kimi_config()
    base = _base_llm_status(config)
    candidates = build_endpoint_candidates(
        config.base_url,
        api_key_source=config.api_key_source,
    )
    default_endpoint = candidates[0] if candidates else config.base_url
    report: dict[str, Any] = {
        "provider": base["provider"],
        "model": base["model"],
        "endpoint": default_endpoint,
        "base_url": config.base_url,
        "api_key_source": config.api_key_source,
        "api_key_masked": _mask_api_key(config.api_key),
        "enabled": base["enabled"],
        "status": "skipped",
        "error": "",
        "probe_latency_ms": 0,
    }
    if not config.api_key:
        report["status"] = "missing_api_key"
        report["error"] = "missing_api_key"
        return report
    if not live_probe:
        report["status"] = "config_only"
        return report
    probe = probe_llm_connection()
    ok = bool(probe.get("last_call_success"))
    report["status"] = "ok" if ok else "error"
    report["error"] = str(probe.get("last_call_error") or "")
    hint = str(probe.get("error_hint") or "").strip()
    if hint:
        report["error_hint"] = hint
    report["probe_latency_ms"] = int(probe.get("probe_latency_ms") or 0)
    used = str(probe.get("endpoint") or "").strip()
    if used:
        report["endpoint"] = used
    return report


def _trim_consultant_summary(text: Any, *, max_chars: int = 200) -> str:
    s = str(text or "").strip().replace("\n", " ")
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def _rows_for_llm_snapshot(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """发给模型的副本：去掉以下划线开头的内部控制字段。"""
    out: list[dict[str, Any]] = []
    for r in items:
        if not isinstance(r, dict):
            continue
        out.append({k: v for k, v in r.items() if not str(k).startswith("_")})
    return out


def complete_demand_quote(
    *,
    product: dict[str, Any],
    items: list[dict[str, Any]],
    inline_prices: list[dict[str, str]],
    structure_text: str = "",
    user_prompt: str = "",
    locked_processing_fee: float | None = None,
    structure_vision_images: Sequence[tuple[str, str]] | None = None,
    structure_checklist: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """LLM completion for the demand-form workflow.

    Each input item already has whatever the demand parser + price KB
    found: ``name``, ``role``, ``spec``, optional ``unit_price`` (from KB
    when hit) and ``kb_hit`` flag.  The model fills in:
        - ``usage`` (always, since 标价表 doesn't carry per-product 用量)
        - ``unit_price`` only when the row is missing a KB hit
        - ``amount`` (= unit_price × usage in CNY)

    KB-hit prices MUST NOT be overwritten — the user explicitly chose
    standard library priority. The system prompt enforces this.
    """
    config = get_kimi_config()
    status = _base_llm_status(config)

    bag_ctx = detect_bag_product(
        product_type=str((product or {}).get("type") or (product or {}).get("product_type") or ""),
        product_name=str((product or {}).get("name") or ""),
        structure_text=structure_text,
        user_prompt=user_prompt,
    )
    skill_meta = resolve_bag_quote_skill(
        product_type=str((product or {}).get("type") or (product or {}).get("product_type") or ""),
        product_name=str((product or {}).get("name") or ""),
        structure_text=structure_text,
        user_prompt=user_prompt,
    )
    if bag_ctx.is_bag:
        status["bag_quote_costing"] = skill_meta
        if isinstance(structure_checklist, dict) and structure_checklist.get("is_bag_product"):
            status["bag_structure_checklist"] = {
                "item_count": len(structure_checklist.get("items") or []),
                "extraction_complete": bool(structure_checklist.get("extraction_complete")),
            }

    if not items:
        return items, status
    if not config.api_key:
        return _fallback_demand_quote(items, status, "missing_api_key")

    locked_note = ""
    if locked_processing_fee is not None and locked_processing_fee > 0:
        locked_note = (
            f"\n【加工费已定】表格中已有明确规则：单件加工费锁定为 **{locked_processing_fee:g}** 元人民币/件。"
            "请勿在输出 JSON 中包含 processing_fee 字段（omit this key）。\n"
        )
        proc_fee_instruction = ""
    else:
        locked_note = ""
        proc_fee_instruction = (
            "\n【加工费评定】须在 JSON 顶层增加数值键 processing_fee（元/件，单值）。\n"
            "- input.product.structure_complexity 若非空，只是业务员填写的粗难度标签，不得把「标准/常规」"
            "直接锁死为固定加工费；必须结合结构说明、图片、材料/配件行重新判断，必要时可跨到相邻档位。\n"
            "- 若 input.product.processing_fee_assessment 有值，这是系统按结构规则给出的初评值；"
            "请把它作为基准复核，而不是机械照抄。若图片或结构说明显示更多/更少工序，可以给出更合理的值。\n"
            "- 参考区间（取下限与上限的几何含义：给出区间内的合理代表值；简单偏低、户外偏高）：\n"
            "  • 简单：基础裁片+简单车缝，无特殊工艺 → **5–10** 元/件；\n"
            "  • 中等：隔层/内袋、多块拼接 → **10–20** 元/件；\n"
            "  • 复杂：多面料拼接、多功能袋 → **20–40** 元/件；\n"
            "  • 户外/特殊：户外结构或外发复杂工艺 → **40–60** 元/件常见。\n"
            "- 必填评估维度（须在心里过一遍再落数）：裁片数；车缝复杂度；配件颗数；结构层数；"
            "产品与结构说明中的风险点。\n"
            "- **若未填写难度**（结构复杂度为空或未识别），则依据上述维度和行业经验**独立严谨判断**，"
            "给出你认为最可能落在正确区间内的 processing_fee（禁止固定写死 12）。\n"
        )

    system_prompt = (
        "【角色】你叫「栢博」，是有约 10 年经验的软包（背包/旅行包/收纳袋）成本核算专家，"
        "说话像懂行的业务经理：清楚、克制、愿意解释费用构成，而不是堆砌数字。\n"
        "\n"
        "【任务】根据输入的成品描述与物料行，补全单件用量与缺失单价，并给出一段给客户的"
        "中文口语化摘要（consultant_summary）。技术字段仍须满足下列硬约束。\n"
        f"{locked_note}"
        "\n"
        "【JSON 输出】仅输出一个 JSON 对象，键包含：\n"
        "  - items：与 input.rows 同序、同条数的数组；每行字段与下列规则一致。\n"
        "  - consultant_summary：简体中文，严格不超过 200 字（含标点）。"
        "面向客户说明：成本主要落在哪些物料、占比大致感受（可用「约」「主要」等含糊词，"
        "禁止捏造未在 rows 出现的具体金额/百分比）；可给 1 条务实降本或替料思路。"
        "若信息不足则一句话说明尚缺何种信息即可。\n"
        f"{proc_fee_instruction}"
        "\n"
        "硬约束（与角色无关，必须遵守）：\n"
        "1. kb_hit 为 true 的行的 unit_price 一律不得改写 — 公司以知识库标价为准。\n"
        "2. 每一行须有带单位的用量数值（码/PCS/SET/套/条/米 等），按「一件成品」计。"
        "若 input.rows 里某行已有用量且非 \"-\"，视为业务在表/结构说明中已给定，**必须保持**该数字与单位，仅用其计算小计，不得改为 1 码或 1 套敷衍。\n"
        "3. kb_hit 为 false 时给出尽力而为的人民币单价文案（如 12元/码、1.2元/PCS）。\n"
        "4. amount = 单价数值 × 用量数值（人民币小计）。\n"
        "5. 凡由模型补出的字段对应 *_ai 标为 true；知识库单价相关标记不得擅自改掉。\n"
        "6. 【禁止重复计码】若已有一行名称含「+」「及」或同时出现网布/EVA 与 x-pac 等，"
        "表示**夹层/复料合一描述**，不得再对其中的 X-PAC、DCF 等主面料单独按「整码」计费；"
        "若 rows 中仍有单独短行的同面料 SKU，应将**该行用量压到 0 或合并进复合行**，避免双计。"
        "拉链/织带写了「元/米」「元/码」时，用量须用**米或码**对应长度，禁止写 1 套=整条长度价而不给米数。\n"
        "7. 【面料反用／反面】仅表示同款面料翻面当外观，属于**工艺说明**。"
        "禁止再输出一条「××面料反用」独立主料并按 1 码/1 套与主料行双倍计价；应写进主料行的备注，用量只算一次。\n"
        "8. 【单价与用量单位须同类】标价写 码²/㎡/m² 时用量必须是面积（码²或㎡），"
        "不得把「仅线性码长」当面积去乘 元/码²；反之 元/线性码也不应与只有面积单位的用量混乘。"
        "若当前行无法对齐则宁可不写、少写 amount，禁止用不匹配单位硬算小计。\n"
        "9. 【计算方式 calc_note — 必填】items 每一行必须输出字符串字段 calc_note（单行、禁止换行，≤240 个中文字符），"
        "风格须与业务员 BOM 成本细表完全一致（对齐图二列「单个用量·规格算法」）："
        "**算式链条优先**：分项构件 + 厘米尺寸代入（可多段 +）+ ÷10000 换㎡（若适用）+ 损耗/排版系数（如 ×1.3）"
        "+ 若有线性码须写出㎡÷门幅→米→÷0.9144≈码；拉链写 cm→米或 cm→码换算。"
        "好例：「包身=[(24×48×2)+(14×48×2)+(24×14)]÷10000=0.399㎡；损耗30%，0.399×1.3=0.52㎡」「拉链总长≈100cm≈1.1码」。"
        "拉链/绳/织带写清按哪几道边或袋口/通道长度；五金写几颗/几处/是否成套。\n"
        "**必须利用** input.structure_description：从中**摘取与该物料名/角色对应**的一句或半句，**重写**成上述「分项+尺寸+损耗」句式（可把文中尺寸抄进 calc_note）；"
        "**即使** input.rows 里该行已有旧的 calc_note 字段（套话或说明文），也必须在输出中用图二句式**改写覆盖**。\n"
        "若 input 中有表格结果说明、图片/OCR 文本、附件链接标题或链接旁备注，必须把其中与该物料相关的有效信息纳入判断；"
        "calc_note 写给业务/核价人员看，只保留可核对的部位、尺寸、门幅、周长、数量、损耗/余量和取值依据，禁止出现「系统推算」「系统近似」「模型推断」「未计排版损耗」等内部或免责字样。\n"
        "结构说明里若写了收纳/分层/开口/贴片位置，只可写进**语义相关**的物料行，**严禁**把同一段「收纳系统…拉链…」说明文不加改写地复制到多行。\n"
        "**10.【用量↔calc_note 绑定】凡该行 usage_ai=true（含你从「-」或占位补成数字），calc_note 必须与用量同源可追溯：**"
        "不得出现「用量写 1.0 线性码」但 calc_note 完全不交代如何从尺寸/门幅/惯例区间推到该码数；"
        "若仅能惯例区间估算，也要写明袋型假设与区间（例「小包主料惯例≈0.45–0.65码当量，取约0.52码」）。\n"
        "**禁止**以下类型占满 calc_note（系统占位语，不是你的输出）："
        "「构件分项未载入」「请对照 BOM」「数据源不含」「用量为 AI 估计」「配件类：按表内」「按表内用量×单价」「若要按开孔」「面积类单价：金额=」"
        "等免责套话——除非 structure_description 与 rows 当真无从推断任何几何关系，才可写一句「表内未分项，建议补齐纸样周长」类极简说明。\n"
        "若仅能推断：也要写**具体惯例取样名**（如「卷口拉链按袋口单侧+反折余量」「肩带贴片按背带有效长+接缝」），不得以「请核对」敷衍。\n"
        "\n"
        "用量经验（要紧 — 宁可保守勿虚高）：\n"
        "- 腰包/小包单件：外料/底料合计常见约 0.35–0.65 码当量；**禁止**对每一行主布都填 1.0 码。\n"
        "- 常规背包外料：小包约 0.4–0.6 码，大包约 1.0–1.3 码；里料一般为外料 70%–85%。\n"
        "- 高价进口料（单价≥200元/码 如 X-PAC、DCF 等）：单件 0.30–0.45 码量级，注意拼片共料勿重复加计。\n"
        "- 拉链按实际开口米数；拉头按个；扣具按结构表里真实颗数。\n"
        "- 结构/结构价里若已写明用量数字，直接使用勿再估高。\n"
        "- 存疑时取区间偏低值。\n"
    )
    if bag_ctx.is_bag:
        system_prompt += build_llm_system_prompt_addon(bag_ctx, structure_text)
        if isinstance(structure_checklist, dict) and structure_checklist.get("items"):
            system_prompt += build_bag_structure_llm_addon(structure_checklist)

    vision_pairs = tuple(structure_vision_images or ())
    use_struct_vision = bool(vision_pairs) and os.environ.get(
        "QUOTE_KIMI_STRUCTURE_VISION", "1"
    ).strip().lower() not in {"0", "false", "no", "off"}
    system_prompt_eff = system_prompt
    if use_struct_vision and vision_pairs:
        system_prompt_eff += (
            "\n【附图说明】用户消息附带工作簿嵌入的产品参考图。"
            "请读取图上可见的尺寸标注、开口位置与分层结构，用于补足文字「结构说明」不足之处；看不清勿编造。\n"
        )

    max_vis = 4
    try:
        max_vis = int(os.environ.get("QUOTE_STRUCTURE_VISION_MAX_IMAGES", "4").strip() or "4")
    except ValueError:
        max_vis = 4
    max_vis = max(1, min(max_vis, 8))
    vision_slice = vision_pairs[:max_vis]

    rows_snapshot = _rows_for_llm_snapshot(items)
    struct_cx = ""
    if isinstance(product, dict):
        raw_cx = product.get("structure_complexity") or product.get("structure_complexity_label")
        if raw_cx is not None and str(raw_cx).strip():
            struct_cx = str(raw_cx).strip()[:120]

    user_payload = {
        "product": {**dict(product), "structure_complexity": struct_cx} if isinstance(product, dict) else product,
        "user_request": str(user_prompt or "").strip()[:800],
        "structure_description": structure_text[:4000],
        "structure_inline_prices": inline_prices[:20],
        "rows": rows_snapshot,
        "processing_fee_locked_by_table": locked_processing_fee is not None and locked_processing_fee > 0,
    }
    if isinstance(structure_checklist, dict) and structure_checklist.get("is_bag_product"):
        user_payload["bag_structure_checklist"] = [
            {
                "structure_id": it.get("structure_id"),
                "name": it.get("name"),
                "category": it.get("category"),
                "category_label": it.get("category_label"),
                "source_text": it.get("source_text"),
                "missing_fields": it.get("missing_fields"),
                "estimate_status": it.get("estimate_status"),
                "needs_human_confirm": it.get("estimate_status") in {"needs_manual", "ai_estimated"},
            }
            for it in (structure_checklist.get("items") or [])
            if isinstance(it, dict)
        ]
    user_text_return = (
        "Return JSON with keys items, consultant_summary, and processing_fee "
        "(number, RMB/pc).\n"
        if locked_processing_fee is None
        else "Return JSON with keys items and consultant_summary only (no processing_fee).\n"
    )
    user_text = (
        "Input:\n"
        f"{json.dumps(user_payload, ensure_ascii=False)}\n\n"
        + user_text_return
        + "Shape for items rows (adjust flags per rules):\n"
        '{"items":[{"name":"...","role":"...","spec":"...","usage":"...",'
        '"unit_price":"...","amount":12.34,"calc_note":"圆筒侧片+底片+压胶展开；损耗约15%",'
        '"usage_ai":true,'
        '"unit_price_ai":false,"amount_ai":true}],'
        '"consultant_summary":"……"'
        + (',"processing_fee":15.5}' if locked_processing_fee is None else "}")
        + "\n"
        "Keep order and item count identical to input.rows.\n"
        "For each row, calc_note must distill structure_description into that material only as a BOM-style formula line"
        "(components + measurable segments + wastage); rows must NOT share identical long prose unless both truly reference "
        "the same single component bundle.\n"
        "Prefer concrete numbers copied or derived from structure_description / product dimensions; omit marketing adjectives "
        '("采用/设置/系统"单独成句且无数值时不可取).'
    )
    user_message_content: str | list[dict[str, Any]]
    if use_struct_vision and vision_slice:
        parts: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            for mime, b64 in vision_slice
        ]
        parts.append({"type": "text", "text": user_text})
        user_message_content = parts
        status["structure_vision_attempt"] = True
    else:
        user_message_content = user_text

    req_body = {
        "model": config.model,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 1680 if locked_processing_fee is None else 1480,
        "messages": [
            {"role": "system", "content": system_prompt_eff},
            {"role": "user", "content": user_message_content},
        ],
    }
    req_body.update(_maybe_thinking_field(config.base_url))

    raw, status = _call_kimi_with_fallback(req_body, config, status)
    tried_vision = bool(use_struct_vision and vision_slice)
    err_tag = str(status.get("error") or "")
    vision_retry = tried_vision and (
        raw is None and err_tag not in {"http_401", "http_403", "http_404"}
    )
    if vision_retry:
        status.pop("error", None)
        status["structure_vision_fallback"] = True
        req_body_plain = {
            **req_body,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        req_body_plain.update(_maybe_thinking_field(config.base_url))
        raw, status = _call_kimi_with_fallback(req_body_plain, config, status)
    if raw is not None:
        status.pop("error", None)
    if raw is None:
        return _fallback_demand_quote(items, status, status.get("error") or "network_error")

    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        parsed = _parse_response_content(content)
        completed_rows = parsed.get("items", [])
        cs = _trim_consultant_summary(parsed.get("consultant_summary"))
        if cs:
            status["consultant_summary"] = cs
        if locked_processing_fee is None:
            raw_pf = parsed.get("processing_fee")
            try:
                if raw_pf is not None:
                    pfv = float(raw_pf)
                    if 0 < pfv < 5000:
                        status["suggested_processing_fee"] = round(pfv, 2)
            except (TypeError, ValueError):
                pass
        if not isinstance(completed_rows, list):
            return _fallback_demand_quote(items, status, "invalid_response_shape")
    except Exception:
        return _fallback_demand_quote(items, status, "parse_error")

    merged = _merge_demand_rows(items, completed_rows)
    if any(isinstance(r, dict) and r.get("llm_suggested_amount") is not None for r in merged):
        status["llm_rejected_fields"] = ["final_amount_must_be_local_formula"]
    status["used"] = True
    return merged, status


def synthesize_bom_from_new_quote_text(
    user_prompt: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str, list[int]]:
    """根据「尺寸+材料+算价」类纯文字生成 BOM 骨架，供后续 KB 命中与 complete_demand_quote。"""
    config = get_kimi_config()
    status: dict[str, Any] = _base_llm_status(config)
    up = str(user_prompt or "").strip()
    if not up:
        status["error"] = "empty_prompt"
        status["error_message"] = "描述为空。"
        return [], status, "", "", [300]
    if not config.api_key:
        status["error"] = "missing_api_key"
        status["error_message"] = (
            "未配置 KIMI API，无法根据文字生成物料表。请上传 BOM 表格，或配置 KIMI_API_KEY 后重试。"
        )
        return [], status, "", "", [300]

    system_prompt = (
        "【角色】你是软包成本核算助手「栢博」。只输出一个 JSON 对象，不得含 Markdown。\n"
        "【任务】用户会给出成品外形尺寸与面料/辅料要求，请列出单件成品的 BOM（约 4–12 行）。\n"
        "必须包含用户点名的主面料；拉链、扣具、织带、里布等按常识补充。\n"
        "每行字段：name（具体物料名）、role（主料/里布/辅料/拉链/扣具 等）、"
        "spec（规格或幅宽，可估）。不要编造精确单价与用量，单价与用量阶段填 \"-\"。\n"
        "另输出：product_name（短品名）、product_size（把用户尺寸整理成一句中文）、"
        "quantities 为整数数组（首元素为默认起订件数，未写数量时用 [300]）。\n"
        "顶层键名固定：product_name, product_size, quantities, items。"
    )
    req_body = {
        "model": config.model,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 1536,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户需求：\n{up[:1200]}\n\n请只返回 JSON。"},
        ],
    }
    req_body.update(_maybe_thinking_field(config.base_url))
    raw, status = _call_kimi_with_fallback(req_body, config, status)
    if raw is None:
        status.setdefault(
            "error_message",
            "模型调用失败，未能根据描述生成物料表。请稍后再试或直接上传表格。",
        )
        return [], status, "", "", [300]
    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        parsed = _parse_response_content(content)
    except Exception:
        status["error"] = "parse_error"
        status["error_message"] = "解析模型输出失败，请稍后重试或上传表格。"
        return [], status, "", "", [300]

    rows = parsed.get("items")
    p_name = str(parsed.get("product_name") or "定制包袋").strip() or "定制包袋"
    p_size = str(parsed.get("product_size") or "-").strip() or "-"
    qty_list: list[int] = [300]
    quantities = parsed.get("quantities")
    if isinstance(quantities, list) and quantities:
        try:
            q0 = int(quantities[0])
            if q0 > 0:
                qty_list = [q0]
        except (TypeError, ValueError):
            pass

    if not isinstance(rows, list) or not rows:
        status["error"] = "empty_items"
        status["error_message"] = "模型未生成有效物料行，请补充面料与尺寸后再试。"
        return [], status, p_name, p_size, qty_list

    bom: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        nm = str(r.get("name") or "").strip()
        if not nm:
            continue
        bom.append(
            {
                "name": nm,
                "role": str(r.get("role") or "辅料").strip() or "辅料",
                "spec": str(r.get("spec") or "-").strip() or "-",
                "usage": "-",
                "unit_price": "-",
                "amount": 0.0,
                "kb_hit": False,
                "kb_score": 0.0,
                "spec_ai": True,
                "usage_ai": False,
                "unit_price_ai": True,
                "amount_ai": False,
                "source": "ai",
            }
        )
    if not bom:
        status["error"] = "empty_bom"
        status["error_message"] = "模型未生成有效物料行，请补充描述后重试。"
        return [], status, p_name, p_size, qty_list

    status["used"] = True
    return bom, status, p_name, p_size, qty_list


def _call_kimi_with_fallback(
    req_body: dict[str, Any],
    config: KimiConfig,
    status: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """Shared endpoint-fallback loop for chat completions. Returns the raw
    response text on success or (None, status_with_error)."""
    import time

    t0 = time.perf_counter()
    network_failures: list[str] = []
    http_failures: list[tuple[int, str, str]] = []
    endpoint_candidates = build_endpoint_candidates(
        config.base_url,
        api_key_source=config.api_key_source,
    )
    max_attempts = _llm_retry_attempts()
    for endpoint in endpoint_candidates:
        for attempt in range(1, max_attempts + 1):
            try:
                raw = send_chat_request(
                    endpoint=endpoint,
                    api_key=config.api_key,
                    body=req_body,
                    timeout_s=config.timeout_s,
                    disable_proxy=False,
                )
                status["base_url"] = _endpoint_base_url(endpoint)
                if attempt > 1:
                    status["retry_attempts"] = attempt
                status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
                _record_last_call(success=True, error="", endpoint=endpoint)
                return raw, status
            except error.HTTPError as exc:
                err_body = _http_error_body(exc)
                http_failures.append((exc.code, endpoint, err_body))
                merge_billing_reminder(status, exc.code, exc)
                err_code = _classify_http_error(exc.code, err_body)
                hint = _openai_model_error_hint(err_code) if _is_openai_config(config) else ""
                if hint:
                    status["error_hint"] = hint
                if exc.code in {401, 403, 404}:
                    break
                if exc.code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                    time.sleep(_llm_retry_backoff_seconds(attempt))
                    continue
                try:
                    raw = send_chat_request(
                        endpoint=endpoint,
                        api_key=config.api_key,
                        body=req_body,
                        timeout_s=config.timeout_s,
                        disable_proxy=True,
                    )
                    status["base_url"] = _endpoint_base_url(endpoint)
                    if attempt > 1:
                        status["retry_attempts"] = attempt
                    status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
                    _record_last_call(success=True, error="", endpoint=endpoint)
                    return raw, status
                except error.HTTPError as inner_exc:
                    ib = _http_error_body(inner_exc)
                    http_failures.append((inner_exc.code, endpoint, ib))
                    merge_billing_reminder(status, inner_exc.code, inner_exc)
                    err_code = _classify_http_error(inner_exc.code, ib)
                    hint = _openai_model_error_hint(err_code) if _is_openai_config(config) else ""
                    if hint:
                        status["error_hint"] = hint
                    if inner_exc.code in {401, 403, 404}:
                        break
                    if inner_exc.code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                        time.sleep(_llm_retry_backoff_seconds(attempt))
                        continue
                    status["base_url"] = _endpoint_base_url(endpoint)
                    status["error"] = err_code
                    status["retry_attempts"] = attempt
                    status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
                    _record_last_call(success=False, error=status["error"])
                    return None, status
                except Exception as inner_exc:
                    network_failures.append(f"{endpoint} (direct): {_format_network_error(inner_exc)}")
                    if attempt < max_attempts:
                        time.sleep(_llm_retry_backoff_seconds(attempt))
                        continue
                    break
            except Exception as inner_exc:
                network_failures.append(f"{endpoint}: {_format_network_error(inner_exc)}")
                try:
                    raw = send_chat_request(
                        endpoint=endpoint,
                        api_key=config.api_key,
                        body=req_body,
                        timeout_s=config.timeout_s,
                        disable_proxy=True,
                    )
                    status["base_url"] = _endpoint_base_url(endpoint)
                    if attempt > 1:
                        status["retry_attempts"] = attempt
                    status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
                    _record_last_call(success=True, error="", endpoint=endpoint)
                    return raw, status
                except error.HTTPError as inner_exc:
                    ib = _http_error_body(inner_exc)
                    http_failures.append((inner_exc.code, endpoint, ib))
                    merge_billing_reminder(status, inner_exc.code, inner_exc)
                    err_code = _classify_http_error(inner_exc.code, ib)
                    hint = _openai_model_error_hint(err_code) if _is_openai_config(config) else ""
                    if hint:
                        status["error_hint"] = hint
                    if inner_exc.code in {401, 403, 404}:
                        break
                    if inner_exc.code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                        time.sleep(_llm_retry_backoff_seconds(attempt))
                        continue
                    status["base_url"] = _endpoint_base_url(endpoint)
                    status["error"] = err_code
                    status["retry_attempts"] = attempt
                    status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
                    _record_last_call(success=False, error=status["error"])
                    return None, status
                except Exception as direct_exc:
                    network_failures.append(f"{endpoint} (direct): {_format_network_error(direct_exc)}")
                    if attempt < max_attempts:
                        time.sleep(_llm_retry_backoff_seconds(attempt))
                        continue
                    break
    if http_failures:
        code, endpoint, last_body = http_failures[-1]
        status["base_url"] = _endpoint_base_url(endpoint)
        err_code = _classify_http_error(code, last_body)
        hint = _openai_model_error_hint(err_code) if _is_openai_config(config) else ""
        if hint:
            status["error_hint"] = hint
        status["error"] = err_code
        merge_billing_reminder(status, code, body=last_body)
        status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        _record_last_call(success=False, error=status["error"])
        return None, status
    err = f"network_error:{'; '.join(network_failures[:2])}" if network_failures else "network_error"
    status["error"] = err
    status["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    _record_last_call(success=False, error=err)
    return None, status


def _merge_ai_calc_note_into_row(row: dict[str, Any], ai_row: dict[str, Any]) -> None:
    from demand_parser import should_prefer_calc_note_incoming

    have = str(row.get("calc_note") or "").strip()
    cand = str(ai_row.get("calc_note") or ai_row.get("calc_method") or "").strip()
    if cand and not _is_missing(cand):
        if should_prefer_calc_note_incoming(have, cand):
            row["calc_note"] = cand


def _merge_demand_rows(
    source_rows: list[dict[str, Any]],
    completed_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for idx, source in enumerate(source_rows):
        row = dict(source)
        ai_row = completed_rows[idx] if idx < len(completed_rows) and isinstance(completed_rows[idx], dict) else {}
        original_name = row.get("name")

        struct_lock_pre = bool(source.get("_structure_usage_lock"))
        sheet_lock_pre = bool(source.get("_sheet_usage_lock"))
        locked_usage_pre = ""
        if struct_lock_pre or sheet_lock_pre:
            lu = str(source.get("usage") or "").strip()
            if lu and not _is_missing(lu):
                locked_usage_pre = lu

        if locked_usage_pre:
            row["usage"] = locked_usage_pre
            row["usage_ai"] = False
            row["usage_from_structure"] = True
            # 模型侧的 amount 常按错误用量算的，必须与锁定用量脱节后重算
            row.pop("amount", None)
            row.pop("amount_ai", None)
        else:
            # Usage is always taken from the model when it gives one — KB carries
            # no per-product 用量 information.
            ai_usage = str(ai_row.get("usage", "")).strip()
            if ai_usage and not _is_missing(ai_usage):
                row["usage"] = ai_usage
                row["usage_ai"] = True

        # Unit price: 业务表/手工/KB 价优先，LLM 仅在缺价时补价。
        from price_source_resolver import has_business_unit_price, row_unit_price_is_authoritative

        kb_hit = _kb_hit_has_valid_unit_price(row)
        ai_price = str(ai_row.get("unit_price", "")).strip()
        if row_unit_price_is_authoritative(row) or has_business_unit_price(row.get("unit_price")):
            row["unit_price_ai"] = False
        elif not kb_hit and ai_price and not _is_missing(ai_price):
            row["unit_price"] = ai_price
            row["unit_price_ai"] = True
            row["price_source"] = "ai_estimate"
            row["pricing_review_required"] = True

        had_llm_amount = _capture_llm_suggested_amount(row, ai_row)
        _finalize_row_amount_local_only(row)
        if had_llm_amount:
            row["llm_amount_rejected"] = True
        _apply_market_estimate_row_meta(row)
        _set_demand_row_source(row)
        row["name"] = original_name
        row.pop("_structure_usage_lock", None)
        row.pop("_sheet_usage_lock", None)
        _merge_ai_calc_note_into_row(row, ai_row)
        merged.append(row)
    return merged


def _set_demand_row_source(row: dict[str, Any]) -> None:
    """Source / price_source 反映单价来源：业务表 > 正式 KB > AI 估算。"""
    from price_source_resolver import (
        PRICE_SOURCE_AI,
        PRICE_SOURCE_KB,
        PRICE_SOURCE_MANUAL,
        PRICE_SOURCE_OVERRIDE,
        PRICE_SOURCE_SHEET,
        infer_price_source,
    )

    ps = infer_price_source(row)
    row["price_source"] = ps
    if ps == PRICE_SOURCE_KB:
        row["source"] = "kb"
    elif ps == PRICE_SOURCE_OVERRIDE:
        row["source"] = "kb"
    elif ps == PRICE_SOURCE_AI:
        row["source"] = "ai"
    else:
        row["source"] = "kb"
    if bool(row.get("unit_price_ai")) or ps == PRICE_SOURCE_AI:
        row["pricing_review_required"] = bool(row.get("pricing_review_required", True))
    elif ps in {PRICE_SOURCE_SHEET, PRICE_SOURCE_MANUAL}:
        row["pricing_review_required"] = bool(row.get("price_conflict_required"))


def _fallback_demand_quote(
    items: list[dict[str, Any]],
    status: dict[str, Any],
    error_code: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """When Kimi is unreachable, fill missing prices via the rule-based
    estimator and assign a reasonable default 用量 of '1套'/'1码' so the
    quote engine still produces a number."""
    status["error"] = error_code
    filled = _apply_local_price_fallback(items)
    for row in filled:
        if bool(row.get("_structure_usage_lock")) or bool(row.get("_sheet_usage_lock")):
            u = str(row.get("usage") or "").strip()
            if u and not _is_missing(u):
                row["usage_ai"] = False
                _backfill_amount_from_unit_price(row)
                row.pop("_structure_usage_lock", None)
                row.pop("_sheet_usage_lock", None)
                _set_demand_row_source(row)
                continue
        if not str(row.get("usage", "")).strip() or _is_missing(str(row.get("usage", "")).strip()):
            du = _default_usage_for_role(str(row.get("role", "")))
            row["usage"] = du
            row["usage_ai"] = True
            cn_prev = str(row.get("calc_note") or "").strip()
            if not cn_prev:
                row["calc_note"] = (
                    f"本地兜底（模型不可用）：用量占位「{du}」仅为保证小计可算，"
                    "非业务员「单个用量·规格算法」展开式；恢复 Kimi 或上传细表后应以表内公式为准。"
                )[:260]
        _backfill_amount_from_unit_price(row)
        _set_demand_row_source(row)
    status["fallback_used"] = True
    status["fallback"] = "rule_based"
    status["used"] = any(
        _as_bool(row.get("usage_ai")) or _as_bool(row.get("unit_price_ai")) or _as_bool(row.get("amount_ai"))
        for row in filled
    )
    return filled, status


def _default_usage_for_role(role: str) -> str:
    role_lower = role.lower()
    if any(kw in role_lower for kw in ("外料", "里料", "辅料", "织带", "绳", "fabric", "lining", "webbing")):
        return "1.0码"
    if any(kw in role_lower for kw in ("拉链", "肩带", "zipper", "strap")):
        return "1套"
    if any(kw in role_lower for kw in ("拉头", "扣", "buckle", "puller")):
        return "1个"
    return "1套"


def autofill_items_with_kimi(
    items: list[dict[str, Any]],
    *,
    user_prompt: str = "",
    structure_vision_images: Sequence[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = get_kimi_config()
    status = _base_llm_status(config)

    if not items:
        return items, status
    if not config.api_key:
        return _fallback_fill_and_mark_status(items, status, "missing_api_key")

    system_content = (
        "【角色】你叫「栢博」，10 年左右软包成本核算背景；输出须为单一 JSON 对象。\n"
        "【任务】仅补全每行空缺字段，已有数值一律保持。缺单价/小计时给人民币尽力估值（软包物料口径），"
        "勿用 \"-\"。每一行若非空还须给出 calc_note：单行≤160字的「构件+取样/周长关系+损耗」式计算说明，"
        "须结合 user request 中可能附带的结构描述或附图做具体归纳，禁止仅写风险提示空句。\n"
        "另 output 须含 consultant_summary：简体中文、≤200 字，面向客户概括本单成本焦点与一条降本/替料建议；"
        "不得编造输入里未出现的具体数字，信息不足可一句话说明。\n"
        "键名固定：items（与输入同序同条数）、consultant_summary。"
    )

    vision_pairs = tuple(structure_vision_images or ())
    use_struct_vision = bool(vision_pairs) and os.environ.get(
        "QUOTE_KIMI_STRUCTURE_VISION", "1"
    ).strip().lower() not in {"0", "false", "no", "off"}
    if use_struct_vision and vision_pairs:
        system_content += (
            "\n【附图说明】用户消息附带产品结构/示意图。若图上可见尺寸、开口或分层信息，用于辅助用量与计价说明；"
            "看不清之处勿编造。\n"
        )
    max_vis = 4
    try:
        max_vis = int(os.environ.get("QUOTE_STRUCTURE_VISION_MAX_IMAGES", "4").strip() or "4")
    except ValueError:
        max_vis = 4
    max_vis = max(1, min(max_vis, 8))
    vision_slice = vision_pairs[:max_vis]

    user_body = (
        "Input rows:\n"
        f"{json.dumps(items, ensure_ascii=False)}\n"
        f"User request context:\n{user_prompt or '-'}\n"
        "Return:\n"
        '{"items":[{"spec":"-","usage":"-","unit_price":"-","amount":null,'
        '"calc_note":"主身裁片用料展开+缝份；拉链按开口总长",'
        '"spec_ai":false,"usage_ai":false,"unit_price_ai":false,"amount_ai":false}],'
        '"consultant_summary":"……"}\n'
        "Keep order and item count identical to input. "
        "For missing price fields, output numeric unit_price text like \"12元/件\" and numeric amount."
    )

    user_message_content: str | list[dict[str, Any]]
    if use_struct_vision and vision_slice:
        parts: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            for mime, b64 in vision_slice
        ]
        parts.append({"type": "text", "text": user_body})
        user_message_content = parts
        status["structure_vision_attempt"] = True
    else:
        user_message_content = user_body

    req_body = {
        "model": config.model,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 960,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_message_content},
        ],
    }
    req_body.update(_maybe_thinking_field(config.base_url))

    raw, status = _call_kimi_with_fallback(req_body, config, status)
    if raw is None:
        return _fallback_fill_and_mark_status(items, status, status.get("error") or "network_error")

    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        parsed = _parse_response_content(content)
        completed_rows = parsed.get("items", [])
        cs = _trim_consultant_summary(parsed.get("consultant_summary"))
        if cs:
            status["consultant_summary"] = cs
        if not isinstance(completed_rows, list):
            return _fallback_fill_and_mark_status(items, status, "invalid_response_shape")
    except Exception:
        return _fallback_fill_and_mark_status(items, status, "parse_error")

    merged = _merge_rows(items, completed_rows)
    merged = _apply_local_price_fallback(merged)
    if any(isinstance(r, dict) and r.get("llm_suggested_amount") is not None for r in merged):
        status["llm_rejected_fields"] = ["final_amount_must_be_local_formula"]
    status["used"] = True
    return merged, status


def _parse_timeout(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        timeout = int(value)
    except ValueError:
        return default
    return max(5, min(timeout, 120))


def _parse_temperature(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    # Moonshot kimi-k2.6 endpoint currently requires temperature=1.
    return 1.0 if parsed != 1.0 else 1.0


def first_non_empty_env(*names: str) -> tuple[str, str]:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped, name
    return "", ""


def normalize_base_url(url: str) -> str:
    normalized = url.strip().rstrip("/")
    if not normalized:
        return DEFAULT_BASE_URL
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _compose_connect_failure_hint(
    *,
    http_failures: list[tuple[int, str, str]],
    network_failures: list[str],
    status_error: str,
) -> str:
    """汇总不可达时的可读原因，避免只显示笼统提示。"""
    parts: list[str] = []
    if http_failures:
        code, ep, lb = http_failures[-1]
        blob = (lb or "").strip().replace("\n", " ")
        if len(blob) > 240:
            blob = blob[:240] + "…"
        parts.append(f"HTTP {code}（{ep}）" + (f"。响应：{blob}" if blob else ""))
    if network_failures:
        parts.append("网络：" + "；".join(network_failures[:4]))
    if not parts and status_error:
        parts.append(status_error)
    head = " ".join(parts) if parts else "未获得上游具体错误。"
    tail = (
        "建议核对：① 已设置 OPENAI_API_KEY（及 OPENAI_BASE_URL / OPENAI_MODEL）；"
        "② 默认 OPENAI_MODEL=gpt-5.3-codex，中转站示例 OPENAI_BASE_URL=https://code.codingplay.top/redeem；"
        "③ 备选 Moonshot 可设 MOONSHOT_BASE_URL=https://api.moonshot.cn/v1 ；"
        "④ 代理环境可尝试关闭系统代理或为该域名设置 NO_PROXY；⑤ Key 与 Base URL 须匹配。"
    )
    return f"{head} {tail}"


def build_endpoint_candidates(base_url: str, *, api_key_source: str = "") -> list[str]:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        normalized = DEFAULT_OPENAI_BASE_URL
    configured_fallbacks = _configured_fallback_base_urls(api_key_source)
    bases: list[str] = []
    seen: set[str] = set()
    for u in (normalized, *configured_fallbacks):
        u = normalize_base_url(u)
        if not u or u in seen:
            continue
        seen.add(u)
        bases.append(u)
    # 非 Moonshot 底座（DeepSeek / 自建网关等）：禁止静默切换域名，避免 Key 错配。
    if not _moonshot_compatible_base(normalized):
        return [f"{u}/chat/completions" for u in bases]

    # Moonshot：在用户配置的域名之外，依次追加官方 .ai / .cn 备选（解决仅一端可达、或环境变量写死单域名失败）。
    candidates: list[str] = []
    seen: set[str] = set()
    for u in (normalized, *configured_fallbacks, *FALLBACK_BASE_URLS):
        u = u.strip().rstrip("/")
        if not u or u in seen:
            continue
        seen.add(u)
        candidates.append(u)
    return [f"{c}/chat/completions" for c in candidates]


def _openai_messages_have_vision(messages: Any) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"image_url", "image"}:
                return True
    return False


def send_chat_request(
    *,
    endpoint: str,
    api_key: str,
    body: dict[str, Any],
    timeout_s: int,
    disable_proxy: bool,
) -> str:
    http_request = request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": LLM_HTTP_USER_AGENT,
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    if disable_proxy:
        opener = request.build_opener(request.ProxyHandler({}))
        with opener.open(http_request, timeout=timeout_s) as resp:
            return resp.read().decode("utf-8")
    with request.urlopen(http_request, timeout=timeout_s) as resp:
        return resp.read().decode("utf-8")


def _format_network_error(exc: Exception) -> str:
    if isinstance(exc, error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            return "timeout"
        return str(reason)
    if isinstance(exc, socket.timeout):
        return "timeout"
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _clip_explain_messages_payload(body: dict[str, Any], *, max_chars: int = 88000) -> dict[str, Any]:
    """追问解释接口若塞进超大 JSON，Moonshot 可能 400（上下文超限）；截断末条 user。"""
    out = copy.deepcopy(body)
    msgs = out.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        return out
    last = msgs[-1]
    if not isinstance(last, dict):
        return out
    content = last.get("content")
    if isinstance(content, str) and len(content) > max_chars:
        tail = "\n…（上下文过长已截断，仅保留前部用于解释）"
        last = {**last, "content": content[: max_chars - len(tail)] + tail}
        out["messages"] = [*msgs[:-1], last]
    return out


def _moonshot_relax_chat_body_variants(body: dict[str, Any]) -> list[dict[str, Any]]:
    """HTTP 400 invalid_request 时依次尝试：去 thinking、锁定 temperature、收紧输出上限。"""
    variants: list[dict[str, Any]] = []
    variants.append(copy.deepcopy(body))

    b1 = copy.deepcopy(body)
    b1.pop("thinking", None)
    b1["temperature"] = 1.0
    variants.append(b1)

    b2 = copy.deepcopy(b1)
    try:
        mt = int(b2.get("max_completion_tokens") or 1536)
    except (TypeError, ValueError):
        mt = 1536
    b2["max_completion_tokens"] = max(256, min(mt, 1024))
    variants.append(b2)

    b3 = copy.deepcopy(b2)
    b3["max_completion_tokens"] = 512
    variants.append(b3)
    return variants


def _send_chat_request_moonshot_with_400_relax(
    *,
    endpoint: str,
    api_key: str,
    body: dict[str, Any],
    timeout_s: int,
    disable_proxy: bool,
) -> str:
    """同一 endpoint 上对 400 做参数降级重试；其它 HTTP 状态立即抛出。"""
    last_400: error.HTTPError | None = None
    for vb in _moonshot_relax_chat_body_variants(body):
        try:
            return send_chat_request(
                endpoint=endpoint,
                api_key=api_key,
                body=vb,
                timeout_s=timeout_s,
                disable_proxy=disable_proxy,
            )
        except error.HTTPError as exc:
            if exc.code == 400:
                last_400 = exc
                continue
            raise
    if last_400 is not None:
        raise last_400
    raise RuntimeError("moonshot 400-relax: no variants")


def _parse_response_content(content: str) -> dict[str, Any]:
    content = content.strip()
    if not content:
        return {"items": []}
    try:
        loaded = json.loads(content)
        if isinstance(loaded, list):
            return {"items": loaded}
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        loaded = json.loads(content[start : end + 1])
        if isinstance(loaded, list):
            return {"items": loaded}
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("No JSON found in content")


def _merge_rows(source_rows: list[dict[str, Any]], completed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for idx, source in enumerate(source_rows):
        row = dict(source)
        ai_row = completed_rows[idx] if idx < len(completed_rows) and isinstance(completed_rows[idx], dict) else {}
        original_name = row.get("name")

        _merge_text_field(row, ai_row, "spec", "spec_ai")
        _merge_text_field(row, ai_row, "usage", "usage_ai")
        _merge_text_field(row, ai_row, "unit_price", "unit_price_ai")
        had_llm_amount = _capture_llm_suggested_amount(row, ai_row)
        row["name"] = original_name
        _finalize_row_amount_local_only(row)
        if had_llm_amount:
            row["llm_amount_rejected"] = True
        _refresh_row_source(row)
        _merge_ai_calc_note_into_row(row, ai_row)
        ai_touch = (
            _as_bool(row.get("usage_ai"))
            or _as_bool(row.get("unit_price_ai"))
            or _as_bool(row.get("spec_ai"))
        )
        if ai_touch:
            reason_in = str(ai_row.get("ai_reason") or "").strip()
            row["ai_reason"] = reason_in or "结构说明或表格占位字段由模型补全，请复核。"
            ac_raw = ai_row.get("ai_confidence")
            ac_num = _parse_float(ac_raw)
            if ac_num is None:
                row.setdefault("ai_confidence", 0.76)
            else:
                ac_norm = ac_num / 100.0 if ac_num > 1.0 else ac_num
                row["ai_confidence"] = max(0.0, min(1.0, float(ac_norm)))
        merged.append(row)
    return merged


def _merge_text_field(row: dict[str, Any], ai_row: dict[str, Any], field: str, flag_field: str) -> None:
    original = str(row.get(field, "")).strip()
    if field == "unit_price" and _looks_invalid_price_text(original):
        original = "-"
        row[field] = "-"
    if field == "spec" and looks_like_technical_key_text(original):
        original = "-"
        row[field] = "-"
    ai_value = str(ai_row.get(field, "")).strip()
    ai_flag = _as_bool(ai_row.get(flag_field))

    if _is_missing(original) and not _is_missing(ai_value):
        if field == "usage" and _is_degenerate_usage_merge_value(ai_value):
            pass
        else:
            row[field] = ai_value
            row[flag_field] = True
    else:
        row[flag_field] = bool(row.get(flag_field, False)) or ai_flag


def _merge_amount_field(row: dict[str, Any], ai_row: dict[str, Any], field: str, flag_field: str) -> None:
    original_value = row.get(field)
    ai_value = ai_row.get(field)
    ai_flag = _as_bool(ai_row.get(flag_field))

    if _is_missing_number(original_value):
        parsed = _parse_float(ai_value)
        if parsed is not None:
            row[field] = parsed
            row[flag_field] = True
            return
    row[flag_field] = bool(row.get(flag_field, False)) or ai_flag


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_signals_area(price: str) -> bool:
    if not str(price or "").strip():
        return False
    p = str(price)
    pl = p.lower()
    return (
        "码²" in p
        or "㎡" in p
        or "m²" in pl
        or ("平方" in p and ("码" in p or "米" in p))
    )


def _usage_signals_area(usage: str) -> bool:
    u = str(usage or "").strip().lower()
    return "码²" in u or "㎡" in u or "m²" in u or ("平方" in u and ("码" in u or "米" in u))


def _usage_is_linear_yard_or_meter(usage: str) -> bool:
    """用量为长度（码或米），且未被标成面积单位。"""
    u = str(usage or "").strip().lower()
    if not u or u in ("-", ""):
        return False
    if _usage_signals_area(u):
        return False
    return bool(re.search(r"\d", u)) and ("码" in u or "米" in u or u.endswith("m"))


def _price_signals_linear_fabric(price: str) -> bool:
    """单价按长度码/米计价的主布类（排除个/套/pcs 等件数价）。"""
    if not str(price or "").strip() or _price_signals_area(price):
        return False
    p = str(price)
    pl = p.lower()
    if "/y" in pl or "/yd" in pl:
        return True
    if any(k in p for k in ("套", "个", "件", "只", "处", "条")) and ("码²" not in p):
        if "pcs" in pl or "pc" in pl or "/set" in pl:
            return False
        # 「7元/条」仍可能是长度条——保守：有条且无码时可当件数
        if "码" not in p and "米" not in p and "/m" not in pl:
            return False
    return ("码" in p and "码²" not in p) or "元/米" in p or "/米" in p or "/m" in pl or "元/m" in pl


def _usage_price_numeric_compatible(price_text: str, usage_text: str) -> bool:
    if not str(price_text or "").strip() or not str(usage_text or "").strip():
        return True
    if str(usage_text).strip() in ("-", ""):
        return True
    pa = _price_signals_area(price_text)
    ua = _usage_signals_area(usage_text)
    pl = _price_signals_linear_fabric(price_text)
    ul = _usage_is_linear_yard_or_meter(usage_text)
    if pa and ul and not ua:
        return False
    if ua and pl and not pa:
        return False
    pt = str(price_text or "").strip()
    ust = str(usage_text or "").strip()
    yp = _linear_price_is_per_yard(pt)
    mp_p = _linear_price_is_per_meter(pt)
    u_m = _usage_quantity_has_meters(ust)
    u_y = _usage_quantity_has_linear_yards_only(ust)
    if ul and pl and (yp ^ mp_p):  # 线性用量仅有一种长度基准与单价对齐时可直乘
        if yp and u_m and not u_y:
            return False
        if mp_p and u_y and not u_m:
            return False
    return True


_YARD_METERS = 0.9144  # 国际码换算米，用于线性「元/Y」与用量「米」对齐
_SQYD_TO_M2 = 0.83612736


def _parse_area_quantity_m2(usage_blob: str) -> float | None:
    """从复合用量（如「152cm / 0.21399㎡」）中取面积数值，统一到㎡。"""
    if not usage_blob or not str(usage_blob).strip():
        return None
    txt = str(usage_blob).strip()
    lo = txt.lower()
    mu = re.search(r"(\d+(?:\.\d+)?)\s*(㎡|m²)", lo, flags=re.I)
    if mu:
        try:
            v = float(mu.group(1))
        except ValueError:
            return None
        return v if 1e-6 < v <= 5000 else None
    mq = re.search(r"(\d+(?:\.\d+)?)\s*码²", txt)
    if mq:
        try:
            yd_sq = float(mq.group(1))
        except ValueError:
            return None
        return round(yd_sq * _SQYD_TO_M2, 8) if 1e-6 < yd_sq <= 5000 else None
    return None


_MISSING_ROLL_ASSUME_CM = 148.0


def _row_eligible_lining_roll_width_assumption(row: dict[str, Any]) -> bool:
    """里布/内里等常无门幅写在行上，㎡×元/码时需假设典型卷宽才能出小计。"""
    blob = " ".join(
        [
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            str(row.get("spec") or ""),
        ],
    ).lower()
    keys = (
        "里布",
        "里料",
        "内里",
        "内衬",
        "ripstop",
        "防撕裂里",
        "尼龙里",
        "涤塔夫",
        "春亚纺",
        "30d",
        "50d",
    )
    return any(k in blob for k in keys)


def _row_eligible_shell_roll_width_assumption(row: dict[str, Any]) -> bool:
    """粗苯/X-PAC 等外料单行常不写门幅，元/码²×线码折算面积时假定典型卷材幅宽。"""
    from material_row_dedupe import _mentions_dch_or_dcf, _mentions_xpac

    blob = " ".join(
        [
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            str(row.get("spec") or ""),
            str(row.get("usage") or ""),
            str(row.get("calc_note") or ""),
            str(row.get("calc_method") or ""),
            _joined_usage_sources_blob(row),
        ],
    ).strip()
    return bool(blob) and (_mentions_dch_or_dcf(blob) or _mentions_xpac(blob))


def _fabric_width_cm_from_row(row: dict[str, Any]) -> float:
    blob = (
        " ".join(
            [
                str(row.get("spec") or ""),
                str(row.get("usage") or ""),
                str(row.get("name") or ""),
                str(row.get("calc_note") or ""),
                str(row.get("calc_method") or ""),
            ],
        ).strip()
    )
    wm = None
    m_lab = re.search(
        r"(?:幅宽|门幅|宽幅)\s*[：:]?\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)?",
        blob,
        flags=re.I,
    )
    if m_lab:
        try:
            wm = float(m_lab.group(1))
        except ValueError:
            wm = None
    if wm is None and re.search(r"(?:cm|厘米)", blob, flags=re.I):
        m_cm = re.search(r"\b(\d{2,4}(?:\.\d+)?)\s*(?:cm|CM|厘米)\b", blob, flags=re.I)
        if m_cm:
            try:
                v = float(m_cm.group(1))
            except ValueError:
                v = 0.0
            if 20 <= v <= 260:
                wm = v
    try:
        fw = float(wm) if wm is not None else 0.0
    except (TypeError, ValueError):
        fw = 0.0
    return fw if 20 <= fw <= 260 else 0.0


def _roll_linear_qty_from_area_for_price(
    price_text: str,
    *,
    area_m2: float,
    row: dict[str, Any],
) -> float | None:
    """卷装布料：线性元/码(或/m) × 用料宽 → 用料长；用量给到㎡时需折算线长。"""
    if area_m2 <= 0:
        return None
    wm = _fabric_width_cm_from_row(row)
    if wm <= 0 and _row_eligible_lining_roll_width_assumption(row):
        wm = _MISSING_ROLL_ASSUME_CM
    if wm <= 0 and _row_eligible_shell_roll_width_assumption(row):
        wm = _MISSING_ROLL_ASSUME_CM
    if wm <= 0:
        return None
    wm_m = wm / 100.0
    run_m = area_m2 / max(1e-9, wm_m)
    pt = str(price_text or "").strip()
    if _linear_price_is_per_yard(pt):
        return round(run_m / _YARD_METERS, 8)
    if _linear_price_is_per_meter(pt):
        return round(run_m, 8)
    if _price_signals_linear_fabric(pt) and not _price_signals_area(pt):
        if "码" in pt and "码²" not in pt:
            return round(run_m / _YARD_METERS, 8)
        lo = pt.lower()
        if re.search(r"/m\b", lo) or "元/米" in pt:
            return round(run_m, 8)
        return round(run_m / _YARD_METERS, 8)
    return None


def _parse_compound_piece_set_price(text: str) -> float | None:
    """如 1.3/0.5/SET → 两件组件合计计价（常见于扣具成套）。"""
    if not text or not text.strip():
        return None
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*(?:/\s*)?(?:SET|HSET|套)\b",
        text.strip(),
        re.I,
    )
    if not m:
        return None
    try:
        return round(float(m.group(1)) + float(m.group(2)), 4)
    except ValueError:
        return None


def _linear_price_is_per_yard(pt: str) -> bool:
    if not pt or _price_signals_area(pt):
        return False
    lo = pt.lower()
    if "/y" in lo or "/yd" in lo:
        return True
    if "元/码" in pt and "码²" not in pt:
        return True
    if "码" in pt and "码²" not in pt and re.search(r"码\s*[＊\*x×]\s*价|每码", pt):
        return True
    return False


def _linear_price_is_per_meter(pt: str) -> bool:
    if not pt or _price_signals_area(pt):
        return False
    lo = pt.lower()
    if "元/米" in pt or "/米" in pt:
        return True
    return bool(re.search(r"/m\b", lo) and not re.search(r"m²|㎡", pt))


def _usage_quantity_has_meters(usage_raw: str) -> bool:
    if not usage_raw or _usage_signals_area(usage_raw):
        return False
    u = str(usage_raw).strip().lower()
    return "米" in u


def _usage_quantity_has_linear_yards_only(usage_raw: str) -> bool:
    if not usage_raw or _usage_signals_area(usage_raw):
        return False
    u = str(usage_raw).strip().lower()
    if "米" in u:
        return False
    return "码" in usage_raw and "码²" not in usage_raw


def _usage_cell_is_centimeter_or_millimeter_line(text: str) -> bool:
    """仅用 cm/mm（或中文厘米/毫米）标长度、未写成「米/码」的用量格子；需换算是米再给元/米计价。"""
    tl = str(text or "").strip().lower()
    if not tl or _looks_like_quantity_ladder(tl):
        return False
    if "毫米" in tl or re.search(r"(?<!\d)\d+(?:\.\d+)?\s*mm\b", tl):
        return True
    if "厘米" in tl:
        return True
    if re.search(r"\d+(?:\.\d+)?\s*cm\b", tl, flags=re.I):
        return True
    return False


def _numeric_cell_to_linear_meters(number: float, raw_original: str) -> tuple[float | None, str]:
    """仅把 mm/cm（含中文毫米/厘米）换成米；码、米等单位保持 None 走原分支。"""
    if number is None or number <= 0:
        return None, ""
    t = str(raw_original or "").strip().lower()
    if "毫米" in t or re.search(r"\d+(?:\.\d+)?\s*mm\b", t, flags=re.I):
        m = round(number / 1000.0, 8)
        if m <= 1e-9:
            return None, ""
        return m, f"{m:g}米"
    if "厘米" in t or re.search(r"\d+(?:\.\d+)?\s*cm\b", t, flags=re.I):
        m = round(number / 100.0, 8)
        if m <= 1e-9:
            return None, ""
        return m, f"{m:g}米"
    return None, ""


def _joined_usage_sources_blob(row: dict[str, Any]) -> str:
    """合并用量格子与计算备注，便于在长文案中检索末尾「X码」「X码²」。"""
    parts: list[str] = []
    for key in ("usage", "calc_note", "calc_method", "spec"):
        v = str(row.get(key) or "").strip()
        if not v or v == "-":
            continue
        parts.append(v)
    return "\n".join(parts)


_LIN_YARD_IN_PROSE = re.compile(r"(\d+(?:\.\d+)?)\s*码(?!²)")


def _lin_meter_in_prose(text: str) -> float | None:
    """从文案中取最后一个「线性米」（跳过平方/立方上下文与「毫米」）。"""
    best: tuple[int, float] | None = None
    tl = text
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*米", tl):
        pre = tl[max(0, m.start() - 12) : m.start()]
        if "平方" in pre or "立方" in pre:
            continue
        post = tl[m.start() : min(len(tl), m.start() + 10)]
        if "毫米" in post:
            continue
        try:
            q = float(m.group(1))
        except ValueError:
            continue
        if not (1e-6 < q <= 50000):
            continue
        if best is None or m.start() >= best[0]:
            best = (m.start(), q)
    if best is None:
        return None
    return best[1]


def _lin_yard_tail_from_prose(text: str) -> float | None:
    hits: list[float] = []
    for m in _LIN_YARD_IN_PROSE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if 1e-6 < v <= 50000:
            hits.append(v)
    return hits[-1] if hits else None


def _row_linear_quantity_and_eff_raw(row: dict[str, Any]) -> tuple[float | None, str]:
    """先认「用量」单列的规整表达式，再在合并文案中取最右侧线长（码优先于米）。

    Returns (quantity_number, canonical_raw_for_checks)：
    「X码」/「X米」用于 `_usage_price_numeric_compatible`。
    """
    primary = str(row.get("usage") or "").strip()
    tl = primary.lower()
    joint = "\n".join([primary, _joined_usage_sources_blob(row)]) if primary else _joined_usage_sources_blob(row)
    jl = joint.lower()

    def pack(q: float, stub: str) -> tuple[float | None, str]:
        stub = stub.strip()
        if q > 1e-6 and stub:
            return q, stub
        return None, ""

    if primary and not _looks_like_quantity_ladder(tl):
        if _looks_like_usage_quantity_text(tl):
            n = _extract_first_number(primary)
            if n is not None and n > 1e-6:
                cm_m, cm_stub = _numeric_cell_to_linear_meters(n, primary)
                if cm_m is not None and cm_stub:
                    return pack(cm_m, cm_stub)
                return pack(n, primary)

    y_candidate = None
    m_candidate = None
    y_last = _lin_yard_tail_from_prose(jl)
    if y_last is not None:
        ys = jl.rfind(f"{y_last}".rstrip("0").rstrip(".") + "码")
        if ys < 0:
            ys = jl.rfind("码")
        y_candidate = (ys if ys >= 0 else 0, y_last)

    lm = _lin_meter_in_prose(jl)
    ms = jl.rfind("米") if lm is not None else -1
    if lm is not None:
        for m_match in re.finditer(r"\d+(?:\.\d+)?\s*米", jl):
            try:
                if abs(float(m_match.group(0).replace("米", "").strip()) - lm) < 1e-9:
                    ms = max(ms, m_match.start())
            except ValueError:
                pass
        m_candidate = (ms, lm)

    if y_candidate is not None and (
        m_candidate is None or y_candidate[0] >= m_candidate[0]
    ):
        q = y_candidate[1]
        qs = "%g码" % q if q != int(q) else f"{int(q)}码"
        return pack(float(q), qs)
    if m_candidate is not None:
        q = m_candidate[1]
        qs = "%g米" % q if q != int(q) else f"{int(q)}米"
        return pack(float(q), qs)

    return None, ""


def _area_m2_from_linear_run(run_meters: float, row: dict[str, Any]) -> float | None:
    if run_meters <= 0:
        return None
    wm = _fabric_width_cm_from_row(row)
    if wm <= 0 and _row_eligible_lining_roll_width_assumption(row):
        wm = _MISSING_ROLL_ASSUME_CM
    if wm <= 0 and _row_eligible_shell_roll_width_assumption(row):
        wm = _MISSING_ROLL_ASSUME_CM
    if wm <= 0:
        return None
    return round(run_meters * (wm / 100.0), 8)


def _area_m2_from_linear_yards(yd: float, row: dict[str, Any]) -> float | None:
    return _area_m2_from_linear_run(float(yd) * float(_YARD_METERS), row)


def _area_m2_derived_from_linear_quantity(
    unit_price_text: str, usage_eff_raw: str, usage_quantity: float, row: dict[str, Any]
) -> float | None:
    if not _price_signals_area(unit_price_text):
        return None
    if usage_quantity <= 0 or not usage_eff_raw.strip():
        return None
    if _usage_signals_area(str(usage_eff_raw)):
        return None
    if _usage_quantity_has_linear_yards_only(usage_eff_raw):
        return _area_m2_from_linear_yards(usage_quantity, row)
    if _usage_quantity_has_meters(usage_eff_raw):
        return _area_m2_from_linear_run(usage_quantity, row)
    return None


def _amount_fill_from_area_squared(
    *,
    unit_price_text: str,
    unit_price_value: float,
    area_m2: float,
) -> float | None:
    """面积单价 × 面积：自动区分 元/㎡ 与 元/码²（缺省视作码²）。"""
    if area_m2 <= 0:
        return None
    pt = str(unit_price_text or "")
    lo = pt.lower()
    if "㎡" in pt or "m²" in lo:
        return round(unit_price_value * area_m2, 2)
    return round(unit_price_value * (area_m2 / _SQYD_TO_M2), 2)


def _converted_linear_quantity_for_price_unit(price_text: str, usage_raw: str, qty: float) -> float | None:
    """仅在「明码/Y 或 元/米」且用量为另一线性单位时用 0.9144 折算。"""
    if qty <= 0:
        return None
    if _usage_price_numeric_compatible(price_text, usage_raw):
        return qty
    pt = str(price_text or "").strip()
    ur = str(usage_raw or "").strip()
    yp = _linear_price_is_per_yard(pt)
    mp = _linear_price_is_per_meter(pt)
    if yp and _usage_quantity_has_meters(ur):
        return round(qty / _YARD_METERS, 6)
    if mp and _usage_quantity_has_linear_yards_only(ur):
        return round(qty * _YARD_METERS, 6)
    return None


def _sanitize_row_amount_for_price_usage_mismatch(row: dict[str, Any]) -> None:
    """避免 元/码² × 线性码长 等设备级错误乘法：清掉不可靠小计，交给回填或留空。"""
    upt = str(row.get("unit_price") or "").strip()
    ust = str(row.get("usage") or "").strip()
    joint_blob = _joined_usage_sources_blob(row).strip()
    mega_blob = (ust + "\n" + joint_blob).strip() if ust else joint_blob

    if upt in ("", "-"):
        return
    if ust in ("", "-"):
        if _unit_price_requires_usage_multiplier(upt):
            row.pop("amount", None)
            row["amount_ai"] = False
            _backfill_amount_from_unit_price(row)
        return

    area_m2 = _parse_area_quantity_m2(mega_blob)
    strict_u = _extract_usage_quantity(ust) if ust else None
    lin_q, lin_stub = _row_linear_quantity_and_eff_raw(row)
    uq: float | None = strict_u if strict_u is not None else lin_q
    ust_for_compat = ust
    if strict_u is None and lin_stub:
        ust_for_compat = lin_stub

    qty_check = area_m2 if (area_m2 is not None and area_m2 > 0) else uq
    if qty_check is None:
        return
    if qty_check <= 0:
        row.pop("amount", None)
        row["amount_ai"] = False
        _backfill_amount_from_unit_price(row)
        return
    if _usage_price_numeric_compatible(upt, ust_for_compat):
        if (
            area_m2 is not None
            and area_m2 > 0
            and _price_signals_area(upt)
        ):
            cp = _parse_compound_piece_set_price(upt)
            pv = cp if cp is not None else _extract_first_number(upt)
            if pv is not None and pv > 0:
                filled = _amount_fill_from_area_squared(
                    unit_price_text=upt,
                    unit_price_value=float(pv),
                    area_m2=area_m2,
                )
                if filled is not None:
                    current = _parse_float(row.get("amount"))
                    if current is None or abs(float(current) - float(filled)) > 0.01:
                        row["amount"] = filled
                        row["amount_ai"] = True
        return
    if (
        area_m2 is not None
        and area_m2 > 0
        and _price_signals_linear_fabric(upt)
        and not _price_signals_area(upt)
    ):
        roll_q = _roll_linear_qty_from_area_for_price(upt, area_m2=area_m2, row=row)
        if roll_q is not None and roll_q > 0:
            cp = _parse_compound_piece_set_price(upt)
            pv = cp if cp is not None else _extract_first_number(upt)
            if pv is not None and pv > 0:
                row["amount"] = round(float(pv) * float(roll_q), 2)
                row["amount_ai"] = True
            return
    row.pop("amount", None)
    row["amount_ai"] = False
    _backfill_amount_from_unit_price(row)


def _is_missing(text: str) -> bool:
    return text == "" or text == "-"


def _unit_price_requires_usage_multiplier(price_text: str) -> bool:
    """按码/㎡/PCS 计价的单价不能以「整张单价」当小计，除非给了有效用量或为整套一口价。"""
    if _parse_compound_piece_set_price(price_text):
        return False
    pt = str(price_text or "").strip().lower()
    if not pt:
        return False
    # 不包含「件/套」：常见为按件一口价（用量常为「-」表示单行一件）
    if re.search(r"元\s*/\s*(码²|㎡|m²|码(?!\s*[²2])|米|pcs|pc|公斤|千克|kg)\b", pt):
        return True
    if re.search(r"/\s*(码²|㎡|m²|码(?!\s*[²2])|米|pcs|pc|kg)\b", pt):
        return True
    if re.search(r"/\s*y(d)?\b", pt):
        return True
    return False


def _is_degenerate_usage_merge_value(text: str) -> bool:
    """模型回填的「0码」等会破坏后续金额逻辑，视为未补全用量。"""
    if _is_missing(text):
        return False
    n = _extract_usage_quantity(text)
    if n is not None and n <= 0:
        return True
    s = str(text).strip().lower()
    return bool(re.fullmatch(r"0(?:\.0+)?\s*(码²|码|m²|㎡|米|m|套|个|pcs|pc)?", s))


def _is_missing_number(value: Any) -> bool:
    if value is None:
        return True
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return True


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _backfill_amount_from_unit_price(row: dict[str, Any]) -> None:
    amount_value = _parse_float(row.get("amount"))
    if amount_value is not None and amount_value > 0 and not _row_has_checkable_numeric_price_usage(row):
        return

    if _is_structure_or_split_market_candidate(row):
        from material_inference import is_pending_inference_usage_text

        usage_pending = str(row.get("usage") or "").strip()
        if is_pending_inference_usage_text(usage_pending) or _extract_usage_quantity(usage_pending) is None:
            row["amount"] = 0.0
            row["amount_ai"] = True
            row["exclude_from_cost"] = True
            row["amount_in_cost"] = False
            return

    unit_price_text = str(row.get("unit_price", "")).strip()
    if _looks_invalid_price_text(unit_price_text):
        return

    compound = _parse_compound_piece_set_price(unit_price_text)
    unit_price_value: float | None = compound
    if unit_price_value is None:
        unit_price_value = _extract_first_number(unit_price_text)
    if unit_price_value is None or unit_price_value <= 0:
        return

    usage_primary_cell = str(row.get("usage") or "").strip()
    if usage_primary_cell:
        strict_cell_qty = _extract_usage_quantity(usage_primary_cell.lower())
        if strict_cell_qty is not None and strict_cell_qty <= 0:
            row["amount"] = 0.0
            row["amount_ai"] = True
            return

    usage_primary = str(row.get("usage") or "").strip()
    joint_blob = _joined_usage_sources_blob(row).strip()
    mega_blob = (usage_primary + "\n" + joint_blob).strip() if usage_primary else joint_blob

    usage_pick, ust_eff_pick = _row_linear_quantity_and_eff_raw(row)
    usage_quantity = usage_pick
    usage_raw = ust_eff_pick if ust_eff_pick else usage_primary

    area_m2 = _parse_area_quantity_m2(mega_blob)
    if (
        (area_m2 is None or area_m2 <= 0)
        and usage_quantity is not None
        and usage_quantity > 0
        and _price_signals_area(unit_price_text)
    ):
        deriv = _area_m2_derived_from_linear_quantity(
            unit_price_text, usage_raw, usage_quantity, row
        )
        if deriv is not None and deriv > 0:
            area_m2 = deriv

    if (
        area_m2 is not None
        and area_m2 > 0
        and _price_signals_area(unit_price_text)
    ):
        filled = _amount_fill_from_area_squared(
            unit_price_text=unit_price_text,
            unit_price_value=float(unit_price_value),
            area_m2=area_m2,
        )
        if filled is not None:
            row["amount"] = filled
            row["amount_ai"] = True
            return

    roll_from_area = (
        _roll_linear_qty_from_area_for_price(
            unit_price_text,
            area_m2=area_m2,
            row=row,
        )
        if (area_m2 is not None and area_m2 > 0)
        else None
    )
    eff_qty: float | None = None

    if roll_from_area is not None and roll_from_area > 0:
        eff_qty = roll_from_area
    elif usage_quantity is not None and usage_quantity > 0:
        adj = _converted_linear_quantity_for_price_unit(unit_price_text, usage_raw, usage_quantity)
        if adj is not None:
            eff_qty = adj
        elif not _usage_price_numeric_compatible(unit_price_text, usage_raw):
            return

    if eff_qty is not None and eff_qty > 0:
        row["amount"] = round(unit_price_value * eff_qty, 2)
        if not _kb_hit_has_valid_unit_price(row):
            row["amount_ai"] = True
        return

    if usage_quantity is not None:
        if usage_quantity <= 0:
            row["amount"] = 0.0
            if not _kb_hit_has_valid_unit_price(row):
                row["amount_ai"] = True
            return
        if _usage_price_numeric_compatible(unit_price_text, usage_raw):
            row["amount"] = round(unit_price_value * usage_quantity, 2)
            if not _kb_hit_has_valid_unit_price(row):
                row["amount_ai"] = True
            return
        return

    if _unit_price_requires_usage_multiplier(unit_price_text):
        return

    row["amount"] = round(unit_price_value, 2)
    if not _kb_hit_has_valid_unit_price(row):
        row["amount_ai"] = True


def _row_has_checkable_numeric_price_usage(row: dict[str, Any]) -> bool:
    unit_price_text = str(row.get("unit_price") or "").strip()
    usage_text = str(row.get("usage") or "").strip()
    if not unit_price_text or not usage_text or usage_text in {"-", "—", "/"}:
        return False
    unit_price_value = _parse_compound_piece_set_price(unit_price_text)
    if unit_price_value is None:
        unit_price_value = _extract_first_number(unit_price_text)
    if unit_price_value is None or unit_price_value <= 0:
        return False
    if _parse_area_quantity_m2(usage_text) is not None and _price_signals_area(unit_price_text):
        return True
    return _extract_usage_quantity(usage_text) is not None and _usage_price_numeric_compatible(
        unit_price_text,
        usage_text,
    )


def _signals_secondary_duplicate_fabric_markup(row: dict[str, Any]) -> bool:
    blob = (_joined_usage_sources_blob(row).strip() + "\n" + str(row.get("name") or "")).strip()
    if "非独立用料" in blob:
        return True
    return "并入工艺备注" in blob


def _fabric_charge_family_token(name: str) -> str:
    from material_row_dedupe import _mentions_dch_or_dcf, _mentions_xpac

    nm = str(name or "").strip()
    if _mentions_dch_or_dcf(nm):
        return "DYNEEMA_FAB"
    if _mentions_xpac(nm):
        return "XPAC"
    return ""


def reconcile_fabric_charge_totals(items: list[dict[str, Any]]) -> None:
    """在全局视角下回填长文案用量；若「工艺备注/非独立」行与同族主料已计费，则不再二次算账。"""
    if not isinstance(items, list):
        return
    primary_paid_tokens: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        tok = _fabric_charge_family_token(str(raw.get("name") or ""))
        if not tok:
            continue
        av = _parse_float(raw.get("amount"))
        if av is None or av <= 1e-6:
            continue
        if _signals_secondary_duplicate_fabric_markup(raw):
            continue
        primary_paid_tokens.add(tok)

    suppressed: set[int] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if not _signals_secondary_duplicate_fabric_markup(raw):
            continue
        tok = _fabric_charge_family_token(str(raw.get("name") or ""))
        if tok and tok in primary_paid_tokens:
            raw.pop("amount", None)
            raw["amount_ai"] = False
            suppressed.add(id(raw))

    for raw in items:
        if not isinstance(raw, dict):
            continue
        if id(raw) in suppressed:
            raw["amount"] = 0.0
            raw["amount_ai"] = False
            continue
        _backfill_amount_from_unit_price(raw)
        _sanitize_row_amount_for_price_usage_mismatch(raw)


def _extract_first_number(text: str) -> float | None:
    cleaned = str(text or "").replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _extract_usage_quantity(value: Any) -> float | None:
    text = str(value or "").strip().lower()
    if not text or _looks_like_quantity_ladder(text):
        return None
    if not _looks_like_usage_quantity_text(text):
        return None
    # cm/mm 用量在 _row_linear_quantity_and_eff_raw 中折成米，避免 strict_u=30 被当成 30 米
    if _usage_cell_is_centimeter_or_millimeter_line(text):
        return None
    return _extract_first_number(text)


def _looks_like_quantity_ladder(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if _parse_compound_piece_set_price(str(text or "")) is not None:
        return False
    if "/" not in normalized and "\\" not in normalized and "," not in normalized and "，" not in normalized:
        return False
    if re.search(r"(qty|quantity|数量)", normalized):
        return True
    parts = [part.strip() for part in re.split(r"[\\/,\|，]+", normalized) if part.strip()]
    numeric_parts = [part for part in parts if re.fullmatch(r"\d+(?:\.\d+)?", part)]
    return len(numeric_parts) >= 2


def _looks_like_usage_quantity_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    # Treat as quantity only when the text itself is a numeric expression
    # (optionally followed by a unit), e.g. "1条", "1.3码²", "2 pcs".
    return bool(
        re.fullmatch(
            r"\d+(?:\.\d+)?\s*(?:"
            r"码²|码|m²|㎡|米|m|条|套|个|只|处|片|kg|g|pcs|pc|pair|yd²|yd"
            r"|cm|mm|厘米|毫米"
            r")?",
            normalized,
            flags=re.I,
        )
    )


def _looks_invalid_price_text(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in INVALID_PRICE_TEXTS:
        return True
    if _looks_like_quantity_ladder(normalized):
        return True
    return _extract_first_number(normalized) is None


def _has_usable_unit_price(value: str) -> bool:
    text = str(value or "").strip()
    if _looks_invalid_price_text(text):
        return False
    num = _extract_first_number(text)
    return num is not None and num > 0


def _kb_hit_has_valid_unit_price(row: dict[str, Any]) -> bool:
    if not bool(row.get("kb_hit")):
        return False
    if _as_bool(row.get("unit_price_ai")):
        return False
    return _has_usable_unit_price(str(row.get("unit_price") or ""))


MARKET_ESTIMATE_NOTE = "市场估算，需人工复核"
STRUCTURE_GAP_AI_ESTIMATE_NOTE = "AI估算价，待管理员复核"


def _is_structure_gap_row(row: dict[str, Any]) -> bool:
    return bool(row.get("from_structure_gap_hint"))


def _is_structure_or_split_market_candidate(row: dict[str, Any]) -> bool:
    if _is_structure_gap_row(row):
        return True
    st = str(row.get("source_type") or "").strip()
    if st in {"structure_inferred", "image_inferred"}:
        return True
    name = str(row.get("name") or "")
    if bool(row.get("from_bag_structure_extraction")) or "结构待核" in name or "推理待核" in name:
        return True
    if str(row.get("recognition_status") or "").strip() == "split":
        return True
    if row.get("_source_combined_name"):
        return True
    return False


def _needs_market_unit_price_estimate(row: dict[str, Any]) -> bool:
    if not _is_structure_or_split_market_candidate(row):
        return False
    return not _kb_hit_has_valid_unit_price(row)


def _apply_market_estimate_row_meta(row: dict[str, Any]) -> None:
    """结构待核/拆分行在补价后标记 AI 估算与人工复核提示。"""
    if not _needs_market_unit_price_estimate(row):
        return
    up = str(row.get("unit_price") or "").strip()
    if _looks_invalid_price_text(up):
        return
    row["unit_price_ai"] = True
    row["amount_ai"] = True
    cn = str(row.get("calc_note") or "").strip()
    if MARKET_ESTIMATE_NOTE not in cn:
        row["calc_note"] = f"{cn}；{MARKET_ESTIMATE_NOTE}" if cn else MARKET_ESTIMATE_NOTE


def _default_market_usage_for_row(row: dict[str, Any]) -> str:
    from material_inference import pending_inference_usage_label

    name = str(row.get("name") or "").strip()
    if _is_structure_or_split_market_candidate(row) or "推理待核" in name or "结构待核" in name:
        return pending_inference_usage_label(name, row)
    joined = " ".join(
        [
            name.lower(),
            str(row.get("role", "")).strip().lower(),
            str(row.get("calc_note", "")).strip().lower(),
            str(row.get("recognition_reason", "")).strip().lower(),
        ]
    )
    if any(keyword in joined for keyword in ("弹力绳", "反光绳", "松紧绳", "橡筋绳", "织带", "webbing", "cord")):
        return "1米"
    if any(keyword in joined for keyword in ("插扣", "d扣", "d环", "调节扣", "梯扣", "猪鼻扣", "拉头", "扣具", "buckle", "puller")):
        return "1个"
    return "1个"


def _usage_from_structure_quantity_text(row: dict[str, Any]) -> str:
    unit_pattern = r"码²|码|m²|㎡|米|m|条|套|个|只|处|片|pcs|pc|pair|yd²|yd|cm|mm|厘米|毫米"
    for field in ("name", "usage", "_source_combined_name"):
        text = str(row.get(field) or "").strip()
        if not text:
            continue
        match = re.search(rf"\d+(?:\.\d+)?\s*(?:{unit_pattern})", text, flags=re.I)
        if match:
            return match.group(0).strip()
    return ""


def _ensure_market_estimate_usage(row: dict[str, Any]) -> None:
    if not _is_structure_or_split_market_candidate(row):
        return
    kb_priced = _kb_hit_has_valid_unit_price(row)
    usage = str(row.get("usage") or "").strip()
    if usage and not _is_missing(usage):
        from material_inference import is_pending_inference_usage_text

        if re.fullmatch(r"1\s*套", usage, flags=re.I) or usage in {"一套", "1组", "一组"}:
            row["usage"] = _default_market_usage_for_row(row)
            if not kb_priced:
                row["usage_ai"] = True
        elif is_pending_inference_usage_text(usage):
            if not kb_priced:
                row["usage_ai"] = True
        return
    row["usage"] = _usage_from_structure_quantity_text(row) or _default_market_usage_for_row(row)
    if not kb_priced:
        row["usage_ai"] = True


def _fallback_fill_and_mark_status(
    items: list[dict[str, Any]],
    status: dict[str, Any],
    error_code: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status["error"] = error_code
    filled = _apply_local_price_fallback(items)
    status["fallback_used"] = True
    status["fallback"] = "rule_based"
    status["used"] = any(_as_bool(row.get("unit_price_ai")) or _as_bool(row.get("amount_ai")) for row in filled)
    return filled, status


def _refresh_recognition_after_invalid_kb_fill(row: dict[str, Any]) -> None:
    """知识库仅命中名称但无有效单价、已走市场估算时，避免仍显示「知识库命中」。"""
    if not _as_bool(row.get("unit_price_ai")):
        return
    had_kb_name_hit = bool(row.get("kb_hit")) or bool(str(row.get("kb_matched_name") or "").strip())
    if not had_kb_name_hit:
        return
    row["kb_hit"] = False
    status = str(row.get("recognition_status") or "").strip()
    if status in {"", "matched"}:
        row["recognition_status"] = "split" if _is_structure_or_split_market_candidate(row) else "candidate_review"
        row["recognition_reason"] = "知识库无有效单价，已用市场估算"


def _apply_local_price_fallback(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for source in items:
        if not isinstance(source, dict):
            continue
        row = dict(source)
        _ensure_market_estimate_usage(row)
        unit_price_text = str(row.get("unit_price", "")).strip()
        if not _kb_hit_has_valid_unit_price(row) and _looks_invalid_price_text(unit_price_text):
            estimate = _estimate_unit_price_text(row)
            if estimate:
                row["unit_price"] = estimate
                row["unit_price_ai"] = True
                _refresh_recognition_after_invalid_kb_fill(row)
        _backfill_amount_from_unit_price(row)
        if _as_bool(row.get("unit_price_ai")) and _needs_market_unit_price_estimate(row):
            _apply_market_estimate_row_meta(row)
        elif _as_bool(row.get("unit_price_ai")) and (
            bool(row.get("kb_matched_name")) or str(row.get("recognition_reason") or "").startswith("知识库无有效单价")
        ):
            row["amount_ai"] = True
            cn = str(row.get("calc_note") or "").strip()
            if MARKET_ESTIMATE_NOTE not in cn:
                row["calc_note"] = f"{cn}；{MARKET_ESTIMATE_NOTE}" if cn else MARKET_ESTIMATE_NOTE
        _refresh_row_source(row)
        merged.append(row)
    return merged


def _apply_structure_gap_process_usage_defaults(row: dict[str, Any]) -> None:
    if not _is_structure_gap_row(row):
        return
    usage = str(row.get("usage") or "").strip()
    if usage and not _is_missing(usage):
        return
    blob = " ".join(
        [
            str(row.get("name") or "").strip().lower(),
            str(row.get("calc_note") or "").strip().lower(),
            str(row.get("role") or "").strip().lower(),
        ]
    )
    if any(keyword in blob for keyword in ("丝印", "烫印", "热转", "印刷", "刺绣", "logo")):
        row["usage"] = "1处"
        row["usage_ai"] = True
    elif any(keyword in blob for keyword in ("车缝", "缝纫", "加工", "工艺费")):
        row["usage"] = "1道工序"
        row["usage_ai"] = True
    elif any(keyword in blob for keyword in ("织带", "webbing", "包边")):
        row["usage"] = "1条"
        row["usage_ai"] = True
    else:
        row["usage"] = "1处"
        row["usage_ai"] = True


def _apply_structure_gap_row_cost_flags(row: dict[str, Any]) -> None:
    if not _is_structure_gap_row(row):
        return
    from material_row_validity import structure_gap_row_ready_for_cost

    if structure_gap_row_ready_for_cost(row):
        row["exclude_from_cost"] = False
        row["amount_in_cost"] = True
        row["structure_gap_pending_pricing"] = False
        row["needs_manual_confirm"] = True
        row["pricing_review_required"] = True
        if any(_as_bool(row.get(k)) for k in ("usage_ai", "unit_price_ai", "amount_ai")):
            row["recognition_reason"] = "AI估算用量/单价，待管理员复核"
            cn = str(row.get("calc_note") or "").strip()
            if STRUCTURE_GAP_AI_ESTIMATE_NOTE not in cn:
                row["calc_note"] = f"{cn}；{STRUCTURE_GAP_AI_ESTIMATE_NOTE}" if cn else STRUCTURE_GAP_AI_ESTIMATE_NOTE
            if _needs_market_unit_price_estimate(row) or _as_bool(row.get("unit_price_ai")):
                _apply_market_estimate_row_meta(row)
    else:
        row["exclude_from_cost"] = True
        row["amount_in_cost"] = False
        row["structure_gap_pending_pricing"] = True


def finalize_structure_gap_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """结构缺项：本地规则 + 知识库行情估算用量/单价，并标记待复核。"""
    staged: list[dict[str, Any]] = []
    for source in items:
        if not isinstance(source, dict):
            continue
        row = dict(source)
        if _is_structure_gap_row(row):
            _apply_structure_gap_process_usage_defaults(row)
        staged.append(row)
    filled = _apply_local_price_fallback(staged)
    out: list[dict[str, Any]] = []
    for row in filled:
        if _is_structure_gap_row(row):
            _apply_structure_gap_row_cost_flags(row)
        out.append(row)
    return out


def prepare_structure_rows_for_market_estimate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill visible market estimates for structure/split/gap candidates before confirmation."""
    return finalize_structure_gap_rows(items)


def _estimate_unit_price_text(row: dict[str, Any]) -> str:
    joined = " ".join(
        [
            str(row.get("name", "")).strip().lower(),
            str(row.get("spec", "")).strip().lower(),
            str(row.get("usage", "")).strip().lower(),
        ]
    )
    usage = str(row.get("usage", "")).strip()
    unit = "元/处"

    if any(keyword in joined for keyword in ("插扣", "d扣", "d环", "调节扣", "梯扣", "猪鼻扣", "扣具", "buckle")):
        return _format_price_text(0.6, "元/个")
    if any(keyword in joined for keyword in ("拉头", "puller")):
        return _format_price_text(0.3, "元/个")
    if any(keyword in joined for keyword in ("弹力绳", "反光绳", "松紧绳", "橡筋绳", "cord")):
        return _format_price_text(2.5, "元/米")
    if any(keyword in joined for keyword in ("织带", "webbing")):
        if "米" in usage or "m" in usage.lower():
            return _format_price_text(1.2, "元/米")
        return _format_price_text(1.5, "元/条")
    if any(keyword in joined for keyword in ("水壶袋", "网袋", "侧袋")):
        return _format_price_text(2.0, "元/个")
    if any(keyword in joined for keyword in ("背垫", "腰封", "肩带", "顶包", "翻盖")):
        return _format_price_text(3.6, "元/套")
    if any(keyword in joined for keyword in ("补强", "加固")):
        return _format_price_text(3.0, "元/处")
    if "dcf" in joined or "dch" in joined:
        return "95元/码²"
    if "x-pac" in joined or "xpac" in joined:
        return "240元/码"
    if "牛津布" in joined or "600d" in joined or "210d" in joined:
        return "14元/码²"
    if any(keyword in joined for keyword in ("网布", "网布料", "网格料", "eva", "海绵")):
        return "12元/码²"
    if any(keyword in joined for keyword in ("外料", "outer", "shell fabric", "fabric")):
        return "80元/码²"
    if any(keyword in joined for keyword in ("里料", "lining")):
        return "5元/码²"
    if any(keyword in joined for keyword in ("拉链", "zipper")):
        unit = "元/条"
        return _format_price_text(7.9, unit)
    if any(keyword in joined for keyword in ("拉头", "puller")):
        unit = "元/个"
        return _format_price_text(1.2, unit)
    if any(keyword in joined for keyword in ("肩带", "织带", "webbing", "strap")):
        unit = "元/套"
        return _format_price_text(3.6, unit)
    if any(keyword in joined for keyword in ("布标", "label")):
        unit = "元/个"
        return _format_price_text(1.5, unit)
    if any(keyword in joined for keyword in ("吊牌", "hangtag")):
        unit = "元/个"
        return _format_price_text(0.8, unit)
    if any(keyword in joined for keyword in ("包装", "packing", "package", "纸箱", "pe袋")):
        unit = "元/套"
        return _format_price_text(1.5, unit)
    if any(keyword in joined for keyword in ("logo", "丝印", "烫印", "热转印", "刺绣", "反光")):
        unit = "元/处"
        return _format_price_text(4.0, unit)
    if any(keyword in joined for keyword in ("车缝", "缝纫", "加工费", "工艺费")):
        unit = "元/处"
        return _format_price_text(3.0, unit)
    if any(keyword in joined for keyword in ("加固", "辅料", "reinforce", "trim")):
        unit = "元/处"
        return _format_price_text(3.0, unit)
    if any(keyword in joined for keyword in ("扣具", "插扣", "d环", "buckle")):
        unit = "元/套"
        return _format_price_text(2.5, unit)

    usage_number = _extract_usage_quantity(usage)
    if usage_number is not None and usage_number > 0:
        return _format_price_text(2.0, "元/单位")
    return ""


def _format_price_text(value: float, unit: str) -> str:
    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value))}{unit}"
    return f"{value:.2f}{unit}"


def _refresh_row_source(row: dict[str, Any]) -> None:
    if _kb_hit_has_valid_unit_price(row):
        row["source"] = "kb"
        row["unit_price_ai"] = False
        row["amount_ai"] = False
        return
    has_ai_fields = any(
        _as_bool(row.get(flag))
        for flag in ("spec_ai", "usage_ai", "unit_price_ai", "amount_ai")
    )
    if has_ai_fields:
        row["source"] = "ai"
        return
    source = str(row.get("source", "")).strip().lower()
    row["source"] = "ai" if source in {"ai", "model"} else "kb"


def looks_like_technical_key_text(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    if "_" in normalized and normalized.replace("_", "").isalnum():
        return True
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", normalized):
        return True
    return normalized.endswith(("_name", "_code", "_id", "_type", "_flag", "_material"))


def explain_quote_advisory(
    *,
    user_question: str,
    focused_quote_json: str,
    recent_quotes_json: str,
) -> tuple[str, dict[str, Any]]:
    """Free-form explanation for follow-up questions; no re-quote."""
    config = get_kimi_config()
    status: dict[str, Any] = _base_llm_status(config)
    if not config.api_key:
        return (
            "未配置可用的 Kimi/Moonshot API Key，我无法用模型口述解释；"
            "请先展开报价卡里的「📋 查看计算过程」，或检查环境变量 KIMI_API_KEY / MOONSHOT_API_KEY。",
            status,
        )

    req_body = {
        "model": config.model,
        # 与 complete_demand_quote 一致：kimi-k2.6 等模型要求固定 temperature=1，传 0.5 会 400，
        # 前端表现为「追问」整条链路失败而主核算仍可用。
        "temperature": config.temperature,
        "max_completion_tokens": 1536,
        "messages": [
            {
                "role": "system",
                "content": (
                    "【身份】你是「栢博」，有大约 10 年背包/软包 OEM 报价与成本拆解经验的外部顾问口吻"
                    "（专业、耐心、不油腻）。你既讲清数字出处，也会对客户的质疑给出可落地的解释与建议。\n"
                    "\n"
                    "【事实边界】仅能根据用户粘贴的报价 JSON 摘要与会话索引作答；勿捏造摘要里不存在的单价、"
                    "数量或总价。如需对方补充信息（例如对照厂的报价分项），直接说出口。\n"
                    "\n"
                    "【风格】简体中文；可先给 2–4 句总括，再用短列表展开。避免机械的「综上」套话。\n"
                    "\n"
                    "【对不同意图的回答策略】\n"
                    "- 追问单价/用量从何而来：逐项对应 detail_sample 中出现的物料名与字段，区分「知识库标价」"
                    "与「模型补全/估算」（说明估算依据的大类行情区间即可，不写虚假精确比价）。\n"
                    "- 质疑或比价（如比别人贵）：语气专业但不防御 —— "
                    "先简要认可『对比很有道理，价差常见』；再从材料档次/进口与国产、用量松紧、工艺复杂度、"
                    "毛利档位、EXW vs FOB 口径、模具摊销档位等拆解「可能差别来自哪里」；"
                    "最后给 1–2 条可执行的降本或替料路径并点明风险。若摘要无法支持结论，写明需何种对照数据。\n"
                    "- 替料或降本：在满足功能与安全前提下分项建议，写明适用场景与让步点。\n"
                    "\n"
                    "除非用户明确要求英文，否则始终中文输出。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "## 用户追问\n"
                    f"{user_question.strip()}\n\n"
                    "## 当前聚焦的一份报价摘要(JSON)\n"
                    f"{focused_quote_json or '{}' }\n\n"
                    "## 本会话最近几次报价索引(JSON)\n"
                    f"{recent_quotes_json or '[]'}\n"
                ),
            },
        ],
    }
    req_body.update(_maybe_thinking_field(config.base_url))
    req_payload = _clip_explain_messages_payload(req_body)

    raw = ""
    network_failures: list[str] = []
    http_failures: list[tuple[int, str, str]] = []
    endpoint_candidates = build_endpoint_candidates(
        config.base_url,
        api_key_source=config.api_key_source,
    )
    for endpoint in endpoint_candidates:
        try:
            raw = _send_chat_request_moonshot_with_400_relax(
                endpoint=endpoint,
                api_key=config.api_key,
                body=req_payload,
                timeout_s=config.timeout_s,
                disable_proxy=False,
            )
            status["base_url"] = _endpoint_base_url(endpoint)
            break
        except error.HTTPError as exc:
            eb = _http_error_body(exc)
            http_failures.append((exc.code, endpoint, eb))
            merge_billing_reminder(status, exc.code, exc)
            if status.get("billing_reminder"):
                return (
                    f"{status['billing_reminder']}（诊断：http_{exc.code}）",
                    status,
                )
            if exc.code in {401, 403, 404, 400}:
                continue
            status["base_url"] = _endpoint_base_url(endpoint)
            status["error"] = f"http_{exc.code}"
            return (
                "（模型暂时不可用，请稍后重试。"
                + f"若反复出现可查接口返回的诊断码：{status['error']}）",
                status,
            )
        except Exception as exc:
            network_failures.append(f"{endpoint}: {_format_network_error(exc)}")
            try:
                raw = _send_chat_request_moonshot_with_400_relax(
                    endpoint=endpoint,
                    api_key=config.api_key,
                    body=req_payload,
                    timeout_s=config.timeout_s,
                    disable_proxy=True,
                )
                status["base_url"] = _endpoint_base_url(endpoint)
                break
            except error.HTTPError as inner_exc:
                ib = _http_error_body(inner_exc)
                http_failures.append((inner_exc.code, endpoint, ib))
                merge_billing_reminder(status, inner_exc.code, inner_exc)
                if status.get("billing_reminder"):
                    return (
                        f"{status['billing_reminder']}（诊断：http_{inner_exc.code}）",
                        status,
                    )
                if inner_exc.code in {401, 403, 404, 400}:
                    continue
                status["base_url"] = _endpoint_base_url(endpoint)
                status["error"] = f"http_{inner_exc.code}"
                return (
                    "（模型暂时不可用，请稍后重试。"
                    + f"若反复出现可查接口返回的诊断码：{status['error']}）",
                    status,
                )
            except Exception as inner_exc:
                network_failures.append(f"{endpoint} (direct): {_format_network_error(inner_exc)}")
                continue
    else:
        if http_failures:
            code, endpoint, lb = http_failures[-1]
            status["base_url"] = _endpoint_base_url(endpoint)
            status["error"] = f"http_{code}"
            merge_billing_reminder(status, code, body=lb)
        else:
            status["error"] = (
                "network_error:" + ("; ".join(network_failures[:2]) if network_failures else "unknown")
            )
        if status.get("billing_reminder"):
            return (
                f"{status['billing_reminder']}（诊断：{status.get('error', '')}）",
                status,
            )
        hint = _compose_connect_failure_hint(
            http_failures=http_failures,
            network_failures=network_failures,
            status_error=str(status.get("error") or ""),
        )
        return (f"（{hint}）", status)

    try:
        payload = json.loads(raw)
        content = str(payload["choices"][0]["message"]["content"] or "").strip()
        if not content:
            status["error"] = "empty_reply"
            return ("（模型返回为空。）", status)
        status["used"] = True
        return content, status
    except Exception:
        status["error"] = "parse_error"
        return ("（解析模型回复失败。）", status)
