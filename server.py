from __future__ import annotations

import atexit
import base64
import copy
import csv
import errno
import json
import mimetypes
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote as url_quote, unquote, urlencode, urlparse

from admin_auth import (
    ROLE_ADMIN,
    authenticate,
    decode_session_from_cookie,
    issue_session_token,
    set_login_cookie_headers,
    set_logout_cookie_header,
    verify_backend_admin_cookie,
)

from dual_intent_route import apply_dual_mode_envelope
from demand_parser import (
    DemandParseResult,
    compute_mold_fee_from_sections,
    enrich_items_calc_note_from_structure,
    enrich_quote_item_rows_with_quotation_calc,
    include_fob_preference_from_user_prompt,
    parse_demand_from_payload,
    quotation_detail_materials_bundle_from_entire_xlsx,
)
from sales_rep_fields import apply_sales_fields_to_payload, merge_quote_sales_from_payload
from text_encoding import deep_repair_strings
from follow_up_merge import (
    build_dimension_hint_from_result,
    is_adjust_quantity_intent,
    is_dimension_follow_up_only,
    is_extra_quantity_calc_intent,
    merge_follow_up_text,
    parse_extra_calc_quantity,
)
from intent_router import is_extra_material_calc_intent, is_new_quote_text_priority
from material_row_dedupe import (
    collapse_fabric_reverse_use_shadow_rows,
    dedupe_composite_overlapping_fabric_rows,
    drop_duplicate_structure_narrative_rows,
    drop_structure_duplicate_markup_rows,
    drop_zero_subtotal_merge_placeholder_rows,
    merge_duplicate_width_label_rows,
)
from material_row_validity import (
    apply_material_validity_layer,
    confirm_material_candidates_for_quote,
    should_skip_knowledge_learn_row,
    summarize_structure_quote_gaps,
    validate_structure_items_for_formal_quote,
)
from structure_usage import (
    apply_structure_usage_hints,
    tighten_small_bag_usage_amounts,
    usage_hint_from_bracket,
)
from piece_area_table import attach_piece_area_calculation


def _load_local_env_file() -> None:
    """从项目根目录 ``.env`` 注入环境变量（不提交仓库；``.gitignore`` 已忽略）。

    默认：仅当进程中**尚无**同名环境变量时才写入（系统变量优先）。
    若进程环境已设置 ``QUOTE_DOTENV_WINS=1``（可先写在系统变量里）：则对密钥/Base URL 等，
    ``.env`` 中的值**覆盖**同名变量 —— 用于纠正 Windows 里误配的旧 MOONSHOT_API_KEY。
    """
    path = Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return
    merge_keys = frozenset(
        {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "LLM_PROVIDER",
            "QUOTE_LLM_PROVIDER",
            "MOONSHOT_API_KEY",
            "KIMI_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "MOONSHOT_BASE_URL",
            "KIMI_BASE_URL",
            "KIMI_MODEL",
            "WECOM_ENABLED",
            "WECOM_CORP_ID",
            "WECOM_AGENT_ID",
            "WECOM_CORP_SECRET",
            "WECOM_OAUTH_REDIRECT_URI",
            "WECOM_PUBLIC_BASE_URL",
            "WECOM_COOKIE_SECURE",
            "COOKIE_SECURE",
            "QUOTE_FRONT_BASE_URL",
            "QUOTE_SERVER_HOST",
            "QUOTE_SERVER_PORT",
            "QUOTE_ADMIN_HTTP_PORT",
            "QUOTE_ADMIN_SERVER_HOST",
        }
    )
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return

    pairs: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            pairs[key] = val

    if not pairs:
        return

    qw_file = str(pairs.get("QUOTE_DOTENV_WINS") or "").strip().lower()
    qw_os = str(os.environ.get("QUOTE_DOTENV_WINS") or "").strip().lower()
    wins = qw_file in {"1", "true", "yes", "on"} or qw_os in {"1", "true", "yes", "on"}

    for key, val in pairs.items():
        if key == "QUOTE_DOTENV_WINS":
            if val.strip():
                os.environ["QUOTE_DOTENV_WINS"] = val.strip()
            continue
        if not val and key in merge_keys:
            continue
        if wins:
            if key in merge_keys:
                if val:
                    os.environ[key] = val
            elif key not in os.environ:
                os.environ[key] = val
        elif key not in os.environ:
            os.environ[key] = val
        elif key in merge_keys and val and not str(os.environ.get(key, "")).strip():
            os.environ[key] = val


_load_local_env_file()

from message_intent import (
    CHAT_STUB_REPLY,
    COMPARE_STUB_REPLY,
    FOLLOW_UP_NO_SESSION_HINT,
    classify_intent,
    should_explain_quote_without_requote,
)
from missing_data_enricher import enrich_missing_quote_data
from material_spec_usage_enricher import (
    enrich_material_rows,
    enrich_payload_material_spec_usage,
    is_missing_spec_usage_value,
)
from kimi_client import (
    autofill_items_with_kimi,
    build_llm_health_report,
    complete_demand_quote,
    get_kimi_status,
    prepare_structure_rows_for_market_estimate,
    reconcile_fabric_charge_totals,
    synthesize_bom_from_new_quote_text,
)
from llm_audit import LlmAuditCollector, build_llm_audit
from core.smart_lookup import enqueue_knowledge_learn_after_rule_miss
from embedding.bge_encoder import embedding_enabled
from price_kb import format_kb_entry_price_display, get_price_kb, KBHit
from price_admin_store import (
    approve_price_exception,
    delete_price_exception,
    delete_price_exceptions_bulk,
    exclude_price_exception,
    export_price_kb_workbook,
    import_price_kb_workbook,
    list_price_exceptions,
    list_price_entries,
    list_price_history,
    price_exception_stats,
    price_admin_stats,
    sync_quote_detail_rows_to_price_kb,
    delete_price_entry,
    upsert_price_entry,
)
from bag_structure_list import patch_structure_checklist_item
from bag_quote_pipeline import apply_bag_quote_preparse
from prompt_intent import (
    DEFERRED_QUOTE_HINT,
    QUOTE_NEEDS_UPLOAD_OR_ITEMS_HINT,
    user_prompt_has_quote_intent,
)
from quote_engine import calculate_quote, reconcile_row_amount_after_unit_price_change
from multi_size_quote import calculate_quote_with_size_variants
from size_variants import enrich_payload_size_variants
from quote_validation_gate import apply_pricing_gate
from quote_upload_storage import (
    admin_delete_all_matching_list_filters,
    admin_delete_quotes_by_ids,
    admin_role_ok,
    approve_saved_quote,
    update_saved_quote_approval,
    batch_hide_quotes_for_sales_user,
    delete_admin_calculated_sheet,
    delete_admin_correction_sheet,
    delete_quote_series,
    finalize_quote_persistence,
    get_admin_calculated_sheet_for_sales,
    get_admin_correction_sheet_for_sales,
    get_sales_original_sheet_for_sales,
    get_my_quote_session_detail,
    get_saved_quote_approval_public,
    get_saved_quote_approval_for_sales_user,
    get_admin_dashboard_stats,
    get_quote_file_record,
    get_saved_quote_admin_bundle,
    init_quote_storage,
    list_my_quotes_for_sales_user,
    list_my_admin_updates_for_sales_user,
    count_unread_admin_updates_for_sales_user,
    list_quote_files_for_quote,
    list_saved_quotes_summaries,
    list_saved_quotes_changes_since,
    mark_sales_admin_update_handled,
    mark_sales_admin_update_viewed,
    persist_admin_calculated_sheet,
    persist_admin_correction_sheet,
    resolve_stored_file_path,
    sales_user_can_access_quote,
    save_admin_quote_feedback,
    upsert_quote_chat_messages,
)
from request_intent_router import (
    ROUTE_ADMIN_ACTION,
    ROUTE_CAPABILITY_HELP,
    ROUTE_CLARIFY,
    ROUTE_COMPARE_EXPLAIN,
    ROUTE_EXPLAIN,
    ROUTE_QA,
    ROUTE_QUOTE_PATCH,
    RequestRoute,
    is_quote_explain_trigger,
    looks_like_business_assistant,
    route_quote_request,
)
from intent_router import looks_like_material_substitution
from sales_auth import (
    clear_sales_session_cookie_header,
    issue_sales_session_token,
    set_sales_session_cookie_header,
    verify_signed_sales_session,
)
from session_quote_context import (
    GLOBAL_SESSION_STORE,
    clear_sales_user_cookie_header_value,
    clear_sales_user_name_cookie_header_value,
    new_sales_user_id,
    new_session_id,
    parse_sales_user_id_from_cookie,
    parse_sales_user_name_from_cookie,
    parse_session_id_from_cookie,
    sales_user_id_from_session,
    sales_user_name_placeholder,
    set_cookie_header_value,
    set_sales_user_cookie_header_value,
    set_sales_user_name_cookie_header_value,
    SESSION_TTL_SECONDS,
)
from wecom_auth import (
    auth_status_payload,
    build_oauth_authorize_url,
    exchange_code_for_profile,
    get_wecom_config,
    is_wecom_browser_user_agent,
    is_wecom_sales_user_id,
    sales_display_name,
    wecom_enabled,
)
from quote_explain import (
    build_explain_response_payload,
    build_local_quote_explanation_text,
    build_process_explainer_payload,
)
from company_payment_accounts import (
    find_exact_company_account,
    get_company_payment_accounts_public,
    reload_company_payment_accounts,
    search_company_accounts,
)
from quote_sheet_i18n import (
    get_quote_sheet_terms_public,
    reload_quote_sheet_terms,
    translate_quote_sheet_fields,
)
from quote_sheet_meta import save_quote_sheet_meta
from quote_sheet_prefill import build_quote_sheet_prefill_payload
from sheet_parser import SheetParseError, parse_sheet_items_from_payload
from sheet_media_enhancer import enrich_items_with_sheet_media_hints
from simple_bom_parser import (
    SimpleBomParseResult,
    parse_simple_bom_from_payload,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
FEEDBACK_FILE = ROOT / "data" / "manual_feedback.csv"
_LOCK_HANDLE = None

_AGENT_GRAPH_LOCK = threading.Lock()
_AGENT_GRAPH_BY_SID: dict[str, tuple[float, dict]] = {}
_AGENT_MAX_IMAGES_PER_TURN = 4


def _short_request_id() -> str:
    return uuid.uuid4().hex[:12]


def _json_log(event: str, **fields: object) -> None:
    payload = {"event": event, "ts": datetime.now().isoformat(timespec="seconds"), **fields}
    try:
        print(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        print(f"[{event}] {fields}")


def _purge_agent_graph_states_unlocked(now: float) -> None:
    dead = [
        sid
        for sid, (touched_at, _) in _AGENT_GRAPH_BY_SID.items()
        if now - touched_at > SESSION_TTL_SECONDS
    ]
    for sid in dead:
        del _AGENT_GRAPH_BY_SID[sid]


def _agent_graph_state_get(sid: str) -> dict | None:
    now = time.time()
    with _AGENT_GRAPH_LOCK:
        _purge_agent_graph_states_unlocked(now)
        row = _AGENT_GRAPH_BY_SID.get(sid)
        if not row:
            return None
        _, data = row
        return copy.deepcopy(data)


def _agent_graph_state_put(sid: str, state: dict) -> None:
    now = time.time()
    safe = json.loads(json.dumps(state, ensure_ascii=False, default=str))
    with _AGENT_GRAPH_LOCK:
        _purge_agent_graph_states_unlocked(now)
        _AGENT_GRAPH_BY_SID[sid] = (now, safe)


def _sync_structure_checklist_into_payload(payload: dict, quote_result: dict) -> None:
    checklist = quote_result.get("structure_checklist")
    if isinstance(checklist, dict) and checklist.get("is_bag_product"):
        payload["structure_checklist"] = copy.deepcopy(checklist)


def _agent_state_from_quote_context(
    *,
    sid: str,
    user_message: str = "",
    payload_snapshot: dict | None = None,
    quote_result: dict | None = None,
) -> dict:
    """Build or refresh LangGraph state from the authoritative local quote session."""
    state = _agent_graph_state_get(sid)
    if state is None:
        try:
            from quotation_agent import empty_quotation_state

            state = dict(empty_quotation_state())
        except ImportError:
            state = {
                "chat_history": [],
                "current_images": [],
                "parameters": {},
                "extracted_data": {},
                "calculation_result": None,
                "user_message": "",
                "assistant_reply": "",
                "final_reply": "",
                "quote_explanation_text": "",
                "vision_analysis_text": "",
                "vision_extracted_patch": {},
                "parameter_delta_note": "",
                "ran_calculator_this_turn": False,
            }
    params = copy.deepcopy(payload_snapshot or {})
    if isinstance(params, dict):
        params.pop("uploaded_sheet", None)
        params.pop("_composer_vision_images", None)
        state["parameters"] = params
    if isinstance(quote_result, dict) and quote_result:
        state["calculation_result"] = copy.deepcopy(quote_result)
    if user_message:
        state["user_message"] = str(user_message)
    return state


def _sync_agent_graph_quote_context(
    *,
    sid: str,
    payload_snapshot: dict,
    quote_result: dict,
    user_message: str = "",
    local_intent: str = "",
) -> None:
    """Mirror successful local quote snapshots into the LangGraph session state."""
    if not sid:
        return
    state = _agent_state_from_quote_context(
        sid=sid,
        user_message=user_message,
        payload_snapshot=payload_snapshot,
        quote_result=quote_result,
    )
    if local_intent:
        state["last_local_quote_intent"] = local_intent
    _agent_graph_state_put(sid, state)


def _resolve_active_quote_id_from_context(sid: str, session_context: dict | None) -> str:
    """Client quote id first, server-side active quote as authoritative fallback."""
    sc = session_context if isinstance(session_context, dict) else {}
    for key in ("currentQuoteId", "activeQuoteId", "quote_id", "quoteId"):
        qid = str(sc.get(key) or "").strip()
        if qid:
            return qid
    return GLOBAL_SESSION_STORE.get_current_quote_id(sid)


def _parse_boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "是", "已确认"}


def _canonical_http_path_only(raw_path_header: str) -> str:
    """Normalize URI path fragment for routing (collapse ``//`` / ``/./`` segments).

    Some reverse proxies rewrite paths with duplicate slashes so exact string compares
    (e.g. ``/admin-api/quotes/batch-delete``) would miss and incorrectly return 404.
    """
    p = (urlparse(raw_path_header).path or "/").strip() or "/"
    segments: list[str] = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if segments:
                segments.pop()
        else:
            segments.append(unquote(part))
    return "/" + "/".join(segments) if segments else "/"


def _static_relative_path(raw_path_header: str) -> str | None:
    """Map ``/static/...`` request path to a relative path under ``STATIC_DIR``.

    Query strings (cache busting) and fragments must not become part of the filename.
    """
    path_only = _canonical_http_path_only(raw_path_header)
    if not path_only.startswith("/static/"):
        return None
    rel = path_only.removeprefix("/static/").lstrip("/")
    return rel or None


_ADMIN_QUOTES_BATCH_DELETE_PATHS = frozenset(
    {
        "/admin-api/quotes/batch-delete",
        "/admin-api/quotes/batch_delete",
    }
)

_ADMIN_QUOTE_NOT_FOUND_MSG = "当前报价不存在或已被删除，请刷新列表后重试"


def _is_admin_api_path(path_only: str) -> bool:
    """Whether path belongs to admin JSON API (for front-site POST delegation)."""
    rp = _canonical_http_path_only(path_only)
    return rp == "/admin-api" or rp.startswith("/admin-api/")


def merge_structure_confirmation_user_items(
    base_items: list[dict],
    patch_rows: object,
) -> list[dict]:
    """将用户在结构确认界面修改的字段合并回服务端解析后的明细行。"""
    if not isinstance(base_items, list) or not base_items:
        return list(base_items) if isinstance(base_items, list) else []
    if not isinstance(patch_rows, list) or not patch_rows:
        return base_items
    max_str = 4000
    out: list[dict] = [dict(r) if isinstance(r, dict) else {} for r in base_items]
    ai_keys = frozenset({"spec_ai", "usage_ai", "unit_price_ai", "amount_ai"})
    appended: list[dict] = []
    for entry in patch_rows:
        if not isinstance(entry, dict):
            continue
        raw_idx = entry.get("index", entry.get("row_index"))
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        is_new_row = idx >= len(out) and not bool(entry.get("deleted") or entry.get("_deleted") or entry.get("delete"))
        if idx < 0 or (idx >= len(out) and not is_new_row):
            continue
        row = {} if is_new_row else out[idx]
        if bool(entry.get("deleted") or entry.get("_deleted") or entry.get("delete")):
            row["exclude_from_cost"] = True
            row["amount_in_cost"] = False
            row["_structure_deleted"] = True
            continue
        touched = False
        unit_price_patched = False
        amount_patched = False
        old_unit_text = str(row.get("unit_price") or "").strip()
        old_amount_value: float | None = None
        try:
            old_amount_value = float(row.get("amount") or 0)
        except (TypeError, ValueError):
            old_amount_value = None
        for key in ("name", "spec", "usage", "unit_price", "amount"):
            if key not in entry:
                continue
            val = entry.get(key)
            if val is None:
                continue
            s = str(val).strip()
            if len(s) > max_str:
                s = s[:max_str]
            row[key] = s
            touched = True
            if key == "unit_price":
                unit_price_patched = True
            if key == "amount":
                amount_patched = True
        if "calc_note" in entry or "calc_method" in entry:
            cn_raw = entry.get("calc_note")
            if cn_raw is None:
                cn_raw = entry.get("calc_method")
            cn = str(cn_raw or "").strip()
            if len(cn) > max_str:
                cn = cn[:max_str]
            row["calc_note"] = cn
            row["calc_method"] = cn
            touched = True
        if touched:
            for mk in ai_keys:
                row.pop(mk, None)
        if unit_price_patched and not amount_patched:
            reconcile_row_amount_after_unit_price_change(
                row,
                old_unit_text=old_unit_text,
                old_amount=old_amount_value,
            )
        if is_new_row and touched and str(row.get("name") or "").strip():
            appended.append(row)
    return [row for row in out + appended if not row.get("_structure_deleted")]


def build_structure_confirmation_payload(
    payload: dict[str, Any],
    *,
    sheet_parse_result: dict | None,
    structure_text: str,
    enrichment_report: dict | None = None,
) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    rows = [r for r in items if isinstance(r, dict)]
    if rows:
        rows = prepare_structure_rows_for_market_estimate(rows)
        rows = enrich_material_rows(
            rows,
            structure_text=str(structure_text or "").strip(),
            product_size=payload.get("product_size")
            if isinstance(payload.get("product_size"), dict)
            else None,
        )
        payload["items"] = rows
    size = payload.get("product_size") if isinstance(payload.get("product_size"), dict) else {}
    missing_usage = sum(1 for r in rows if is_missing_spec_usage_value(r.get("usage")))
    missing_price = sum(1 for r in rows if str(r.get("unit_price") or "").strip() in {"", "-", "—"})
    ai_rows = sum(
        1
        for r in rows
        if any(bool(r.get(k)) for k in ("spec_ai", "usage_ai", "unit_price_ai", "amount_ai"))
    )
    calc_note_rows = sum(1 for r in rows if str(r.get("calc_note") or r.get("calc_method") or "").strip())
    confirmation_rows = []
    for idx, r in enumerate(rows):
        confirmation_rows.append(
            {
                "index": idx,
                "name": str(r.get("name") or "").strip(),
                "spec": str(r.get("spec") or "").strip(),
                "usage": str(r.get("usage") or "").strip(),
                "unit_price": str(r.get("unit_price") or "-").strip() or "-",
                "amount": r.get("amount"),
                "calc_note": str(r.get("calc_note") or r.get("calc_method") or "").strip(),
                "ai": any(bool(r.get(k)) for k in ("spec_ai", "usage_ai", "unit_price_ai", "amount_ai")),
                "recognition_status": str(r.get("recognition_status") or "").strip(),
                "recognition_reason": str(r.get("recognition_reason") or "").strip(),
                "material_clue": str(r.get("material_clue") or "").strip(),
                "source_type": str(r.get("source_type") or "").strip(),
                "inferred_by_ai": bool(r.get("inferred_by_ai")),
                "needs_manual_confirm": bool(r.get("needs_manual_confirm") or r.get("needs_human_confirm")),
            },
        )
    preview = confirmation_rows[:10]
    risks: list[str] = []
    if missing_usage:
        risks.append(f"{missing_usage} 行用量缺失")
    if missing_price:
        risks.append(f"{missing_price} 行单价缺失")
    if ai_rows:
        risks.append(f"{ai_rows} 行含系统补全/估算")
    if structure_text and calc_note_rows == 0:
        risks.append("已识别结构说明，但明细行缺少计算方式绑定")
    er = enrichment_report if isinstance(enrichment_report, dict) else {}
    unresolved_count = int(er.get("unresolved_count") or 0)
    if unresolved_count:
        risks.append(f"{unresolved_count} 个缺失字段仍需复核")

    structure_checklist = payload.get("structure_checklist") if isinstance(payload.get("structure_checklist"), dict) else None
    if isinstance(structure_checklist, dict) and structure_checklist.get("is_bag_product"):
        sc_items = structure_checklist.get("items") or []
        risks.append(f"包类结构清单 {len(sc_items)} 项（skill 提取）")
        leak_n = len(structure_checklist.get("extraction_leaks") or [])
        if leak_n:
            risks.append(f"{leak_n} 个结构词提取漏项")
        pending_n = sum(
            1
            for it in sc_items
            if isinstance(it, dict)
            and it.get("estimate_status") in {"needs_manual", "ai_estimated"}
            and str(it.get("user_status") or "") != "ignored"
        )
        if pending_n:
            risks.append(f"{pending_n} 个结构件待补成本/待确认")

    inf_report = payload.get("material_inference_report") if isinstance(payload.get("material_inference_report"), dict) else {}
    inferred_n = int(inf_report.get("inferred_row_count") or inf_report.get("candidates_added") or 0)
    if inferred_n:
        risks.append(f"{inferred_n} 项结构/图片推理成本候选项（需人工复核）")
    sparse = inf_report.get("sparse_excel_risk")
    if isinstance(sparse, dict) and sparse.get("triggered"):
        risks.append(str(sparse.get("reason") or "Excel 材料行偏少，相对结构/图片复杂度存在漏计风险"))

    resp = {
        "quote_ready": False,
        "reply_type": "structure_confirmation",
        "intent": "STRUCTURE_CONFIRMATION_REQUIRED",
        "assistant_message": "已完成结构预核对，请先确认结构/用量/单价后再生成正式报价。",
        "title": "结构确认后再报价",
        "file_name": str((sheet_parse_result or {}).get("file_name") or ""),
        "product_name": str(payload.get("product_name") or ""),
        "product_size": size,
        "structure_text": structure_text[:1200],
        "item_count": len(rows),
        "calc_note_count": calc_note_rows,
        "ai_row_count": ai_rows,
        "missing_usage_count": missing_usage,
        "missing_price_count": missing_price,
        "risks": risks,
        "items_preview": preview,
        "items_confirmation": confirmation_rows,
        "missing_data_enrichment": er,
    }
    if isinstance(structure_checklist, dict):
        resp["structure_checklist"] = structure_checklist
        resp["structure_items"] = structure_checklist.get("items") or []
        resp["bag_quote_skill"] = payload.get("bag_quote_skill")
        resp["bag_quote_pipeline"] = payload.get("bag_quote_pipeline")
    return resp


def _invoke_agent_quote_explain(
    *,
    sid: str,
    user_message: str,
    payload_snapshot: dict,
    quote_result: dict,
) -> tuple[str, dict | None]:
    """Use LangGraph for explanation flow; fallback remains local and deterministic."""
    try:
        from quotation_agent import invoke_turn
    except ImportError:
        return (
            build_local_quote_explanation_text(
                quote_result,
                user_question=user_message,
                advisory_error="未安装 LangGraph 依赖",
            ),
            None,
        )

    state_in = _agent_state_from_quote_context(
        sid=sid,
        user_message=user_message,
        payload_snapshot=payload_snapshot,
        quote_result=quote_result,
    )
    try:
        state_out = invoke_turn(state_in, user_message=user_message)
    except Exception as exc:  # noqa: BLE001
        return (
            build_local_quote_explanation_text(
                quote_result,
                user_question=user_message,
                advisory_error=str(exc),
            ),
            None,
        )
    _agent_graph_state_put(sid, state_out)
    reply = str(
        state_out.get("final_reply")
        or state_out.get("assistant_reply")
        or state_out.get("quote_explanation_text")
        or ""
    ).strip()
    if not reply:
        reply = build_local_quote_explanation_text(quote_result, user_question=user_message)
    return reply, state_out


def _agent_memory_get(sid: str) -> dict:
    state = _agent_graph_state_get(sid)
    if isinstance(state, dict):
        mem = state.get("quote_followup_memory")
        if isinstance(mem, dict):
            return copy.deepcopy(mem)
    return {}


def _agent_memory_put(sid: str, memory: dict) -> None:
    if not sid:
        return
    state = _agent_graph_state_get(sid) or _agent_state_from_quote_context(sid=sid)
    state["quote_followup_memory"] = copy.deepcopy(memory if isinstance(memory, dict) else {})
    _agent_graph_state_put(sid, state)


def _normalize_agent_turn_images(raw) -> tuple[list[str], str | None]:
    """解析客户端 images 数组：dataURL 或裸 base64；与现有报价附件大小上限对齐。"""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return [], "images 须为字符串数组（base64 或 data:...;base64,...）。"
    out: list[str] = []
    total_decoded = 0
    for x in raw[:_AGENT_MAX_IMAGES_PER_TURN]:
        s = str(x).strip()
        if not s:
            continue
        if s.startswith("data:"):
            idx = s.find("base64,")
            if idx != -1:
                s = s[idx + 7 :].strip()
        s = s.replace("\n", "").replace("\r", "")
        try:
            pad = (-len(s)) % 4
            blob = base64.b64decode(s + ("=" * pad), validate=False)
        except Exception:
            return [], "部分图片 base64 无法解码。"
        total_decoded += len(blob)
        if total_decoded > _QUOTE_MAX_IMAGE_BYTES_CLIENT * _AGENT_MAX_IMAGES_PER_TURN:
            return [], "图片总大小超出上限。"
        out.append(s)
    return out, None


_QUOTE_MAX_COMPOSER_ATTACHMENTS = 3
_QUOTE_MAX_IMAGE_BYTES_CLIENT = 10 * 1024 * 1024
_QUOTE_MAX_SHEET_BYTES_CLIENT = 20 * 1024 * 1024
_ATTACHMENT_SHEET_SUFFIXES = frozenset({".xlsx", ".xls", ".csv", ".tsv"})
_ATTACHMENT_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_ATTACHMENT_SHEET_MIMES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "text/csv",
        "application/csv",
        "text/tab-separated-values",
    }
)
_ATTACHMENT_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


def _classify_composer_attachment(name: str, mime_raw: str) -> str | None:
    """Return \"sheet\", \"image\", or None."""
    nm = str(name or "").strip()
    suffix = Path(nm).suffix.lower()
    mime = str(mime_raw or "").strip().split(";")[0].strip().lower()

    sheet_by_suffix = suffix in _ATTACHMENT_SHEET_SUFFIXES
    image_by_suffix = suffix in _ATTACHMENT_IMAGE_SUFFIXES
    sheet_by_mime = mime in _ATTACHMENT_SHEET_MIMES or mime == "application/octet-stream"
    image_by_mime = mime in _ATTACHMENT_IMAGE_MIMES

    if sheet_by_suffix and not image_by_suffix:
        return "sheet"
    if image_by_suffix and not sheet_by_suffix:
        return "image"
    if sheet_by_suffix and image_by_suffix:
        return "sheet" if nm.lower().rsplit(".", 1)[-1] in {"xlsx", "xls", "csv", "tsv"} else "image"
    if sheet_by_mime and not image_by_mime:
        return "sheet"
    if image_by_mime:
        return "image"
    if sheet_by_suffix:
        return "sheet"
    if image_by_suffix:
        return "image"
    return None


def _image_mime_normalized(name: str, mime_raw: str) -> str:
    mime = str(mime_raw or "").strip().split(";")[0].strip().lower()
    if mime in _ATTACHMENT_IMAGE_MIMES:
        return mime
    suffix = Path(str(name or "")).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def normalize_quote_request_message_and_attachments(payload: dict) -> str | None:
    """合并 message_text；解析 attachments[] 为 uploaded_sheet / _composer_vision_images。返回错误文案或 None。"""
    if not isinstance(payload, dict):
        return None

    msg_text = str(payload.get("message_text") or "").strip()
    if msg_text:
        payload["user_prompt"] = msg_text
        payload["prompt"] = msg_text

    raw_atts = payload.get("attachments")
    if raw_atts is None:
        payload.pop("_composer_vision_images", None)
        return None
    if not isinstance(raw_atts, list):
        return "attachments 须为非空数组，或省略该字段。"
    if len(raw_atts) == 0:
        payload.pop("attachments", None)
        payload.pop("_composer_vision_images", None)
        return None
    if len(raw_atts) > _QUOTE_MAX_COMPOSER_ATTACHMENTS:
        return f"附件个数超过上限（最多 {_QUOTE_MAX_COMPOSER_ATTACHMENTS} 个）。"

    sheet_blob: dict[str, str] | None = None
    visions: list[tuple[str, str]] = []

    for idx, raw in enumerate(raw_atts):
        if not isinstance(raw, dict):
            return f"attachments[{idx}] 须为对象。"
        fname = str(raw.get("name") or "").strip()
        mime_t = str(raw.get("mime_type") or "").strip()
        b64 = str(raw.get("content_base64") or "").strip()
        if not fname:
            return f"attachments[{idx}] 缺少文件名 name。"
        if not b64:
            return f"附件「{fname}」内容为空。"

        try:
            decoded = base64.b64decode(b64, validate=True)
        except Exception:
            return f"附件「{fname}」Base64 无法解码。"

        kind = _classify_composer_attachment(fname, mime_t)
        if kind is None:
            return (
                f"附件「{fname}」类型不支持。"
                "请使用表格（xlsx / xls / csv）或图片（png / jpg / webp）。"
            )

        if kind == "sheet":
            if len(decoded) > _QUOTE_MAX_SHEET_BYTES_CLIENT:
                return f"表格「{fname}」超过大小上限（{_QUOTE_MAX_SHEET_BYTES_CLIENT // (1024 * 1024)}MB）。"
            if sheet_blob is not None:
                return "单次会话仅支持 1 个表格附件；多张表请分包发送或使用压缩包前先拆单。"
            sheet_blob = {"name": fname, "content_base64": b64}
        else:
            if len(decoded) > _QUOTE_MAX_IMAGE_BYTES_CLIENT:
                return f"图片「{fname}」超过大小上限（{_QUOTE_MAX_IMAGE_BYTES_CLIENT // (1024 * 1024)}MB）。"
            visions.append((_image_mime_normalized(fname, mime_t), b64))

    payload["_composer_vision_images"] = tuple(visions)

    if sheet_blob is not None:
        payload["uploaded_sheet"] = sheet_blob
    else:
        payload.pop("uploaded_sheet", None)

    payload.pop("attachments", None)
    return None


def lock_file_for_port(port: int) -> Path:
    """单实例锁按监听端口拆分，默认端口仍使用 `.server.lock` 兼容旧单机部署。"""
    if port == DEFAULT_HTTP_PORT:
        return ROOT / ".server.lock"
    return ROOT / f".server.lock.{port}"

# 工作台 Web 入口（页面 + /api）仅此一个端口；与 main.py 无关，main 不监听端口。
# 默认刻意避开与本机常见的 8765（易被其它本地工具占用，例如其它采集/演示站），改用 8776。
DEFAULT_HTTP_PORT = 8776
# 独立后台监听端口（0 或环境变量 off 关闭第二监听）
DEFAULT_ADMIN_HTTP_PORT = 8080

QUOTE_TIMEOUT_USER_MESSAGE = (
    "报价生成超时，可能是本地模型或网络不可用，请稍后重试或联系管理员。"
)


class QuoteCalculateTimeoutError(TimeoutError):
    """正式报价核算超过服务端最长等待时间。"""


def _quote_request_timeout_sec() -> float:
    raw = os.environ.get("QUOTE_REQUEST_TIMEOUT_SEC", "120")
    try:
        return max(30.0, min(300.0, float(str(raw).strip())))
    except (TypeError, ValueError):
        return 120.0


def _quote_items_stage_metrics(items: object) -> dict[str, int]:
    rows = items if isinstance(items, list) else []
    gap_rows = summarize_structure_quote_gaps(
        [r for r in rows if isinstance(r, dict)]
    )
    pending = 0
    missing_price = 0
    for gap in gap_rows:
        reasons = gap.get("reasons") if isinstance(gap.get("reasons"), list) else []
        if "待确认" in reasons:
            pending += 1
        if "缺单价" in reasons:
            missing_price += 1
    active = sum(
        1
        for row in rows
        if isinstance(row, dict)
        and not bool(row.get("deleted"))
        and str(row.get("recognition_status") or "").strip() != "ignored"
    )
    return {
        "items": len(rows),
        "active_items": active,
        "pending": pending,
        "missing_price": missing_price,
        "gap_rows": len(gap_rows),
    }


def _log_quote_stage(handler: object, stage: str, **extra: object) -> None:
    trace = getattr(handler, "_dual_quote_trace", None)
    t0 = trace.get("t0") if isinstance(trace, dict) else None
    elapsed = round(time.perf_counter() - float(t0), 3) if t0 else None
    parts = [f"[quote] stage={stage}"]
    if elapsed is not None:
        parts.append(f"elapsed={elapsed}s")
    for key, value in extra.items():
        if value is not None and value != "":
            parts.append(f"{key}={value}")
    print(" ".join(parts), flush=True)


def _calculate_quote_with_guard(handler: object, payload: dict) -> dict:
    item_count = len(payload.get("items") or []) if isinstance(payload.get("items"), list) else 0
    _log_quote_stage(handler, "calculate_quote_start", items=item_count)
    timeout = _quote_request_timeout_sec()
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(calculate_quote_with_size_variants, payload, calculate_quote)
    try:
        result = fut.result(timeout=timeout)
    except FuturesTimeoutError as exc:
        fut.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        _log_quote_stage(handler, "calculate_quote_timeout", timeout_sec=timeout)
        raise QuoteCalculateTimeoutError(QUOTE_TIMEOUT_USER_MESSAGE) from exc
    finally:
        if fut.done():
            pool.shutdown(wait=False, cancel_futures=True)
    _log_quote_stage(handler, "calculate_quote_done", tiers=len(result.get("tiers") or []))
    return result


def _handle_admin_price_delete(
    row_id: str,
    *,
    updated_by: str,
    write_json,
    name: str = "",
    spec: str = "",
    price: str = "",
) -> None:
    """DELETE/POST 共用：从价格库删除一行。"""
    try:
        result = delete_price_entry(
            row_id,
            updated_by=updated_by,
            name=name,
            spec=spec,
            price=price,
        )
    except ValueError as exc:
        write_json({"error": "invalid_request", "message": str(exc)}, status=400)
        return
    except RuntimeError as exc:
        write_json({"error": "price_delete_failed", "message": str(exc)}, status=500)
        return
    write_json(result)


def header_admin_role_allowed() -> bool:
    """本地调试可接受 X-User-Role；企微/生产默认仅信任后台登录 Cookie。"""
    if wecom_enabled():
        return str(os.getenv("QUOTE_ALLOW_HEADER_ADMIN", "0") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return str(os.getenv("QUOTE_ALLOW_HEADER_ADMIN", "1") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def admin_http_access_ok(headers: object) -> bool:
    """管理员：后台登录签名 Cookie；本地/显式开关下才接受 X-User-Role。"""
    cookie = None
    if headers is not None:
        try:
            cookie = headers.get("Cookie")  # type: ignore[union-attr]
        except Exception:
            cookie = None
    if verify_backend_admin_cookie(cookie):
        return True
    if header_admin_role_allowed() and admin_role_ok(headers):
        return True
    return False


def resolve_quote_series_uid(
    sid: str | None,
    payload: dict | None,
    quote_result: dict,
) -> str:
    """同会话追问重算共用 quote_series_uid；新上传表格或文字新开报价则新开 series。"""
    calc_id = str(quote_result.get("quote_id") or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    intent = str(quote_result.get("intent") or "")
    blob = payload.get("uploaded_sheet")
    fresh_sheet = isinstance(blob, dict) and str(blob.get("content_base64") or "").strip()
    if fresh_sheet:
        return calc_id
    if intent == "new_quote_text":
        return calc_id
    if sid:
        stored = GLOBAL_SESSION_STORE.get(sid) or {}
        prev = stored.get("quote_series_uid")
        if isinstance(prev, str) and prev.strip():
            return prev.strip()
    return calc_id


_WECOM_ENTRY_MESSAGE = "请从企业微信进入报价系统"


def _front_wecom_browser_ok(handler: QuoteHandler) -> bool:
    """企微生产模式：仅允许企业微信内置浏览器访问业务员工作台。"""
    if not wecom_enabled():
        return True
    ua = str(handler.headers.get("User-Agent") or "")
    return is_wecom_browser_user_agent(ua)


def _write_front_wecom_browser_required(handler: QuoteHandler) -> None:
    handler.write_json(
        {
            "error": "wecom_browser_required",
            "message": _WECOM_ENTRY_MESSAGE,
            "wecom_enabled": True,
        },
        status=403,
    )


def _redirect_wecom_oauth_error(handler: QuoteHandler, *, error_code: str, message: str) -> None:
    cfg = get_wecom_config()
    base = (cfg.public_base_url if cfg else "/").rstrip("/") or "/"
    qs = urlencode(
        {
            "wecom_auth_error": str(error_code or "wecom_oauth_failed").strip(),
            "wecom_auth_message": str(message or "企业微信登录失败。").strip(),
        }
    )
    handler.send_redirect(f"{base}/?{qs}")


def _resolve_front_sales_identity(handler: QuoteHandler) -> tuple[str, str, bool]:
    """Return (sales_user_id, sales_user_name, authenticated)."""
    handler.ensure_session_id()
    cookie = handler.headers.get("Cookie")
    if wecom_enabled():
        verified = verify_signed_sales_session(cookie)
        if verified:
            sid, name = verified
            if not name:
                name = sales_display_name(sid)
            handler._cookie_sales_user_id = sid
            return sid, name, True
        return "", "", False
    sales_uid = handler.ensure_sales_user_id()
    return sales_uid, sales_user_name_placeholder(sales_uid), True


def _front_sales_identity(handler: QuoteHandler) -> tuple[str, str]:
    sales_uid, sales_name, _ = _resolve_front_sales_identity(handler)
    return sales_uid, sales_name


def _require_front_sales_auth(handler: QuoteHandler) -> tuple[str, str] | None:
    if not _front_wecom_browser_ok(handler):
        _write_front_wecom_browser_required(handler)
        return None
    sales_uid, sales_name, ok = _resolve_front_sales_identity(handler)
    if ok and sales_uid:
        return sales_uid, sales_name
    payload = auth_status_payload(authenticated=False)
    payload["error"] = "auth_required"
    payload["message"] = "请先完成企业微信登录。"
    handler.write_json(payload, status=401)
    return None


def _set_front_sales_cookies(handler: QuoteHandler, sales_user_id: str, sales_user_name: str) -> None:
    sid = str(sales_user_id or "").strip()
    sname = str(sales_user_name or "").strip()
    handler._cookie_sales_user_id = sid
    if wecom_enabled():
        handler._set_sales_session_token = issue_sales_session_token(sid, sname)
        handler._set_sales_user_cookie_id = None
        handler._set_sales_user_name_cookie = None
    else:
        handler._set_sales_user_cookie_id = sid
        handler._set_sales_user_name_cookie = sname
        handler._set_sales_session_token = None


def _persist_quote_with_sales_user(
    handler: QuoteHandler,
    *,
    series_uid: str,
    response: dict[str, Any],
    payload: dict[str, Any] | None,
    sheet_fn: str,
    uploaded_sheet: dict[str, Any] | None,
    user_message: str = "",
) -> bool:
    if wecom_enabled():
        auth = _require_front_sales_auth(handler)
        if auth is None:
            return False
        sales_uid, sales_name = auth
    else:
        sales_uid, sales_name = _front_sales_identity(handler)
    if isinstance(payload, dict) and isinstance(response, dict):
        for key in (
            "structure_text_snapshot",
            "structure_text",
            "product_size",
            "product_size_text",
            "structure_checklist",
        ):
            val = payload.get(key)
            if val is None or val == "":
                continue
            if key not in response or response.get(key) in (None, "", {}):
                response[key] = val
        if isinstance(payload.get("items"), list) and not isinstance(response.get("detail_rows"), list):
            response["detail_rows"] = payload["items"]
        attach_piece_area_calculation(response)
    response["quote_series_uid"] = series_uid
    finalize_quote_persistence(
        quote_series_uid=series_uid,
        quote_result=response,
        uploaded_sheet=uploaded_sheet,
        sheet_original_display_name=sheet_fn,
        sales_user_id=sales_uid,
        sales_user_name=sales_name,
    )
    user_text = str(user_message or "").strip()
    if not user_text and sheet_fn:
        user_text = f"上传报价表：{sheet_fn}"
    try:
        upsert_quote_chat_messages(
            series_uid,
            [
                {
                    "message_id": f"user-{response.get('quote_id')}-turn",
                    "role": "user",
                    "content": user_text,
                    "metadata": {"type": "user_turn", "fileName": sheet_fn},
                },
                {
                    "message_id": f"qc-{response.get('quote_id')}",
                    "role": "assistant",
                    "content": "",
                    "metadata": {
                        "type": "quote_card",
                        "quote_id": response.get("quote_id"),
                        "fileName": sheet_fn,
                    },
                },
            ],
            sales_user_id=sales_uid,
            sales_user_name=sales_name,
        )
    except Exception:
        pass
    return True


_PROCESS_ONLY_PATTERN = re.compile(
    r"(计算过程|过程拆解|怎么算|怎样算|拆分|成本构成|公式是怎样的|逐行|明细怎么来)",
    re.IGNORECASE,
)


def _interaction_wants_process_only(user_message: str, interaction: str) -> bool:
    if interaction == "process":
        return True
    return bool(_PROCESS_ONLY_PATTERN.search(str(user_message or "")))


def _tier_unit_cost(tier: object) -> float:
    if not isinstance(tier, dict):
        return 0.0
    try:
        v = tier.get("cost_before_margin")
        if v is not None:
            return float(v)
        return float(tier.get("total_cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _original_reference_quantity(last_res: dict, base_payload: dict) -> int:
    tiers = last_res.get("tiers") if isinstance(last_res.get("tiers"), list) else []
    if tiers and isinstance(tiers[0], dict):
        q = tiers[0].get("quantity")
        try:
            if q is not None:
                return int(q)
        except (TypeError, ValueError):
            pass
    raw_q = base_payload.get("quantities") if isinstance(base_payload, dict) else None
    if isinstance(raw_q, (list, tuple)) and raw_q:
        try:
            return int(raw_q[0])
        except (TypeError, ValueError):
            pass
    return 0


def _material_total_from_result(res: dict) -> float:
    try:
        return float(res.get("material_total") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_material_key(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _is_generic_calc_note(note: object) -> bool:
    text = str(note or "").strip()
    if not text:
        return True
    generic_hints = (
        "未见「计算方式」",
        "数据源不含「计算方式」",
        "用量为 ai 估计",
        "小计=单价×用量",
        "面料类：",
        "配件类：",
        "请按袋口/开孔",
        "请以业务 bom",
    )
    lowered = text.lower()
    return any(h.lower() in lowered for h in generic_hints)


def _is_specific_calc_note(note: object) -> bool:
    text = str(note or "").strip()
    if not text:
        return False
    if _is_generic_calc_note(text):
        return False
    if any(sym in text for sym in ("+", "＋", "×", "x", "X", "*", "÷")):
        return True
    specific_hints = ("底片", "侧片", "压胶", "袋口", "周长", "开孔", "打结", "损耗", "展开")
    lowered = text.lower()
    return any(h.lower() in lowered for h in specific_hints)


def _annotate_extra_material_detail_rows(
    response: dict,
    row_index: int,
    *,
    old_label: str,
    old_unit_price: str,
    new_label: str,
) -> None:
    rows = response.get("detail_rows")
    if not isinstance(rows, list):
        return
    if row_index < 0 or row_index >= len(rows):
        return
    row = rows[row_index]
    if not isinstance(row, dict):
        return
    row["extra_material_trial"] = True
    row["trial_price_note"] = (
        f"试算替料「{new_label}」单价 {row.get('unit_price', '-')} "
        f"（原「{old_label}」{old_unit_price}）"
    )


def _safe_sync_price_kb_from_quote(response: dict[str, Any]) -> None:
    """报价完成后尝试补入价格库；失败不影响报价返回。"""
    if not isinstance(response, dict) or not response.get("quote_ready"):
        return
    try:
        sync_info = sync_quote_detail_rows_to_price_kb(response, updated_by="agent_auto")
        response["price_kb_sync"] = sync_info
    except Exception as exc:  # noqa: BLE001
        response["price_kb_sync"] = {"error": str(exc)}
        try:
            print(f"[price-kb-sync] failed: {exc}")
        except Exception:
            pass


def _route_fields(route: RequestRoute | None) -> dict[str, Any]:
    if route is None:
        return {}
    return route.as_dict()


def _clarify_response_for_route(
    route: RequestRoute,
    *,
    user_text: str,
    has_active_quote: bool,
    has_upload: bool,
) -> dict[str, Any]:
    from clarify_once import ClarifySpec, build_clarify_response, detect_request_clarify

    spec = detect_request_clarify(
        user_text,
        has_upload=has_upload,
        has_active_quote=has_active_quote,
        route_reason=str(route.route_reason or ""),
    )
    if spec is not None:
        return build_clarify_response(spec)
    reason = str(route.route_reason or "")
    if not has_active_quote:
        return build_clarify_response(
            ClarifySpec(
                reason or "quote_context_missing",
                "请上传表格，或说明产品、数量和主要材料。",
                ("upload_or_bom", "quantity", "material"),
            )
        )
    return build_clarify_response(
        ClarifySpec(
            reason or "follow_up_unclear",
            "请再具体说一下要改哪一项，例如「箱子换5元一个」「数量改300件」。",
            ("patch_target",),
        )
    )


def _maybe_pre_quote_clarify(payload: dict[str, Any]) -> dict[str, Any] | None:
    from clarify_once import build_clarify_response, detect_pre_quote_clarify

    spec = detect_pre_quote_clarify(payload if isinstance(payload, dict) else {})
    if spec is None:
        return None
    return build_clarify_response(spec)


def _qa_response_for_route(user_text: str, *, sid: str = "") -> dict[str, Any]:
    """轻量 RAG 答疑：不进入 calculate_quote。"""
    from qa_rag import answer_qa

    return answer_qa(user_text, sid=sid or None)


def _try_business_assistant_response(
    handler: QuoteHandler,
    user_text: str,
    payload: dict[str, Any],
    *,
    has_active_quote: bool,
    has_upload: bool = False,
) -> bool:
    """业务助手：答疑/解释/替料试算；已写响应则返回 True。"""
    text = str(user_text or "").strip()
    if not text:
        return False
    if has_upload and user_prompt_has_quote_intent(text):
        return False
    if not looks_like_business_assistant(text, has_active_quote=has_active_quote):
        return False

    sid = handler._cookie_session_id or handler.ensure_session_id()
    sc = payload.get("session_context") if isinstance(payload.get("session_context"), dict) else {}

    if has_active_quote and is_quote_explain_trigger(text, True):
        qid = _resolve_active_quote_id_from_context(sid, sc)
        if qid and GLOBAL_SESSION_STORE.validate_quote_id(sid, qid):
            last_res = GLOBAL_SESSION_STORE.get_last_quote_result(sid, qid) or {}
            if isinstance(last_res, dict) and last_res.get("tiers"):
                sync = (
                    last_res.get("price_kb_sync")
                    if isinstance(last_res.get("price_kb_sync"), dict)
                    else None
                )
                st = dict(get_kimi_status()) if isinstance(get_kimi_status(), dict) else {}
                st.setdefault("agent", "quote_explain_local")
                handler.write_json(
                    build_explain_response_payload(
                        last_res,
                        user_question=text,
                        price_kb_sync=sync,
                        llm_status=st,
                    )
                )
                return True

    if has_active_quote and (
        looks_like_material_substitution(text)
        or re.search(r"(便宜多少|会便宜|试算|\d+\s*件)", text, re.I)
    ):
        if handler.handle_session_intent_quote(payload):
            return True

    qa = _qa_response_for_route(text, sid=sid)
    qa.setdefault("reply_type", "business_qa")
    qa["context_state"] = "active_quote" if has_active_quote else "no_quote"
    handler.write_json(qa)
    return True


def _capability_help_response() -> dict[str, Any]:
    message = (
        "我可以帮你做这些：\n"
        "1. 上传 BOM/需求表生成报价。\n"
        "2. 解释报价怎么算、每项成本来自哪里。\n"
        "3. 对比业务员/外部报价和系统报价差异。\n"
        "4. 按数量、单价、加工费、包装费做局部试算。\n"
        "5. 查询材料、工艺、历史价格和价格库信息。\n"
        "6. 信息不够时先帮你确认缺什么。"
    )
    return {
        "quote_ready": False,
        "reply_type": "capability_help",
        "assistant_message": message,
        "intent": "QA",
        "context_state": "no_quote",
        "next_actions": ["upload_bom", "ask_material", "explain_quote"],
        "data": {"capabilities": message.splitlines()},
    }


def apply_user_prompt_quote_overrides(payload: dict) -> None:
    """用户话术中的 FOB/EXW 关键字；美元兑人民币汇价（表里或环境变量）。"""
    if not isinstance(payload, dict):
        return
    user_text = str(payload.get("user_prompt") or payload.get("prompt") or "").strip()
    pref = include_fob_preference_from_user_prompt(user_text)
    if pref is not None:
        payload["include_fob"] = pref
    raw_rate = payload.get("usd_cny_rate")
    if raw_rate is None or (isinstance(raw_rate, str) and not str(raw_rate).strip()):
        try:
            payload["usd_cny_rate"] = float(os.environ.get("QUOTE_USD_CNY_RATE", "7.15"))
        except ValueError:
            payload["usd_cny_rate"] = 7.15
    else:
        try:
            payload["usd_cny_rate"] = float(raw_rate)
        except (TypeError, ValueError):
            payload["usd_cny_rate"] = float(os.environ.get("QUOTE_USD_CNY_RATE", "7.15"))
    if float(payload["usd_cny_rate"] or 0) <= 0:
        payload["usd_cny_rate"] = 7.15


class QuoteHandler(BaseHTTPRequestHandler):
    server_version = "AutoQuoteMVP/0.1"

    def setup(self) -> None:
        super().setup()
        self._set_session_cookie_id: str | None = None
        self._set_sales_user_cookie_id: str | None = None
        self._set_sales_user_name_cookie: str | None = None
        self._set_sales_session_token: str | None = None
        self._cookie_session_id = ""
        self._cookie_sales_user_id = ""
        self._quote_site = getattr(self.server, "_quote_site", "front")

    def ensure_session_id(self) -> str:
        raw = parse_session_id_from_cookie(self.headers.get("Cookie"))
        if raw and len(raw) >= 8:
            self._set_session_cookie_id = raw
            self._cookie_session_id = raw
            return raw
        nid = new_session_id()
        self._set_session_cookie_id = nid
        self._cookie_session_id = nid
        return nid

    def ensure_sales_user_id(self) -> str:
        """Local-dev identity only (WECOM_ENABLED=0). Do not use when WeCom OAuth is on."""
        if wecom_enabled():
            verified = verify_signed_sales_session(self.headers.get("Cookie"))
            if verified:
                self._cookie_sales_user_id = verified[0]
                return verified[0]
            return ""
        raw = parse_sales_user_id_from_cookie(self.headers.get("Cookie"))
        if raw and len(raw) >= 8:
            self._set_sales_user_cookie_id = raw
            self._cookie_sales_user_id = raw
            return raw
        nid = new_sales_user_id()
        self._set_sales_user_cookie_id = nid
        self._cookie_sales_user_id = nid
        return nid

    def send_redirect(self, location: str, *, status: int = 302, extra_headers: list[tuple[str, str]] | None = None) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        if extra_headers:
            for hk, hv in extra_headers:
                self.send_header(hk, hv)
        self.end_headers()

    def require_admin_json_api(self) -> bool:
        """须管理员权限：后台登录 Cookie；本地/显式开关下才接受 X-User-Role。"""
        if admin_http_access_ok(self.headers):
            return True
        self._discard_request_body()
        self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
        return False

    def _admin_client_ip_allowed(self) -> bool:
        raw = os.environ.get("QUOTE_ADMIN_ALLOW_IPS", "").strip()
        if not raw:
            return True
        ip = str(self.client_address[0] if self.client_address else "")
        allowed = {x.strip() for x in raw.split(",") if x.strip()}
        return ip in allowed

    def _front_is_blocked_request(self, path_only: str) -> bool:
        rp = path_only.rstrip("/") or "/"
        if rp.startswith("/admin") or rp.startswith("/admin-api"):
            return True
        if rp.startswith("/api/admin"):
            return True
        if rp.startswith("/static/admin"):
            return True
        if re.match(r"^/api/quotes/([^/]+)/files$", rp) or re.match(
            r"^/api/quotes/files/([^/]+)/download$", rp
        ):
            return True
        return False

    def _discard_request_body(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 0:
            self.rfile.read(length)

    def _front_post_reject_blocked_path(self, path_only: str) -> bool:
        """Front site: reject blocked POST paths at routing entry with JSON 404."""
        rp = path_only.rstrip("/") or "/"
        blocked = self._front_is_blocked_request(path_only)
        if not blocked and re.match(r"^/api/quotes/([^/]+)/approval/?$", rp):
            blocked = True
        if not blocked:
            return False
        self._discard_request_body()
        self.write_json({"error": "not found"}, status=404)
        return True

    def _admin_site_do_GET(self, parsed_req, req_path: str) -> None:
        if req_path == "/admin-api/session":
            sess = decode_session_from_cookie(self.headers.get("Cookie"))
            if sess:
                self.write_json(
                    {"authenticated": True, "role": str(sess.get("role") or "")}
                )
            else:
                self.write_json({"authenticated": False, "role": None})
            return

        if req_path == "/admin-api/stats":
            if not self.require_admin_json_api():
                return
            self.write_json(get_admin_dashboard_stats())
            return

        if req_path == "/admin-api/prices/stats":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            try:
                stats = price_admin_stats()
                stats.update(price_exception_stats())
                self.write_json(stats)
            except Exception as exc:
                self.write_json({"error": "price_kb_unavailable", "message": str(exc)}, status=500)
            return

        if req_path == "/admin-api/price-exceptions":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            qs = parse_qs(parsed_req.query)
            try:
                page = max(1, int(qs.get("page", ["1"])[0]))
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = max(1, min(int(qs.get("page_size", ["30"])[0]), 200))
            except (TypeError, ValueError):
                page_size = 30
            try:
                items, total = list_price_exceptions(
                    page=page,
                    page_size=page_size,
                    search_q=(qs.get("q", [""])[0] or "").strip() or None,
                    status=(qs.get("status", ["open"])[0] or "open").strip() or "open",
                )
            except Exception as exc:
                self.write_json({"error": "price_exceptions_unavailable", "message": str(exc)}, status=500)
                return
            self.write_json({"page": page, "page_size": page_size, "total": total, "items": items})
            return

        if req_path == "/admin-api/prices":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            qs = parse_qs(parsed_req.query)
            try:
                page = max(1, int(qs.get("page", ["1"])[0]))
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = max(1, min(int(qs.get("page_size", ["30"])[0]), 200))
            except (TypeError, ValueError):
                page_size = 30
            try:
                items, total = list_price_entries(
                    page=page,
                    page_size=page_size,
                    search_q=(qs.get("q", [""])[0] or "").strip() or None,
                    status=(qs.get("status", [""])[0] or "").strip() or None,
                )
            except Exception as exc:
                self.write_json({"error": "price_kb_unavailable", "message": str(exc)}, status=500)
                return
            self.write_json({"page": page, "page_size": page_size, "total": total, "items": items})
            return

        if req_path == "/admin-api/prices/history":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            qs = parse_qs(parsed_req.query)
            try:
                limit = max(1, min(int(qs.get("limit", ["50"])[0]), 200))
            except (TypeError, ValueError):
                limit = 50
            try:
                self.write_json({"items": list_price_history(limit=limit)})
            except Exception as exc:
                self.write_json({"error": "price_history_unavailable", "message": str(exc)}, status=500)
            return

        if req_path == "/admin-api/prices/export":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            qs = parse_qs(parsed_req.query)
            updated_by = (qs.get("updated_by", ["admin"])[0] or "admin").strip() or "admin"
            try:
                blob, filename, rows = export_price_kb_workbook(updated_by=updated_by)
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                self.write_json({"error": "export_failed", "message": str(exc)}, status=500)
                return
            except Exception as exc:
                self.write_json({"error": "price_kb_unavailable", "message": str(exc)}, status=500)
                return
            tmp = Path(tempfile.gettempdir()) / f"aq-price-export-{uuid.uuid4().hex}.xlsx"
            try:
                tmp.write_bytes(blob)
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header("Content-Length", str(len(blob)))
                disp = url_quote(filename, safe="")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{disp}")
                self.send_header("X-Price-Kb-Rows", str(rows))
                self.end_headers()
                self.wfile.write(blob)
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            return

        if req_path == "/admin-api/quotes":
            if not self.require_admin_json_api():
                return
            qs = parse_qs(parsed_req.query)
            try:
                page = max(1, int(qs.get("page", ["1"])[0]))
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = max(1, min(int(qs.get("page_size", ["30"])[0]), 100))
            except (TypeError, ValueError):
                page_size = 30
            offset = (page - 1) * page_size
            search_q = (qs.get("q", [""])[0] or "").strip() or None
            date_from = (qs.get("from", [""])[0] or "").strip() or None
            date_to = (qs.get("to", [""])[0] or "").strip() or None
            version_min = None
            vm0 = qs.get("version_min", [None])[0]
            if vm0 is not None and str(vm0).strip() != "":
                try:
                    version_min = int(vm0)
                except (TypeError, ValueError):
                    version_min = None
            status_raw = (qs.get("status", [""])[0] or "").strip().lower()
            status_f = status_raw if status_raw in ("risk", "warn", "normal") else None
            sales_user_q = (qs.get("sales_user_q", [""])[0] or "").strip() or None
            items, total = list_saved_quotes_summaries(
                limit=page_size,
                offset=offset,
                search_q=search_q,
                date_from=date_from,
                date_to=date_to,
                version_min=version_min,
                status=status_f,
                sales_user_q=sales_user_q,
            )
            self.write_json(
                {"page": page, "page_size": page_size, "total": total, "items": items}
            )
            return

        if req_path == "/admin-api/quotes/changes":
            if not self.require_admin_json_api():
                return
            qs = parse_qs(parsed_req.query)
            since = (qs.get("since", [""])[0] or "").strip()
            try:
                change_limit = max(1, min(int(qs.get("limit", ["50"])[0]), 100))
            except (TypeError, ValueError):
                change_limit = 50
            items, new_count = list_saved_quotes_changes_since(since, limit=change_limit)
            self.write_json(
                {
                    "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "since": since,
                    "new_count": new_count,
                    "items": items,
                }
            )
            return

        m_admin_quote = re.match(r"^/admin-api/quotes/([^/]+)$", req_path)
        if m_admin_quote:
            if not self.require_admin_json_api():
                return
            qida = unquote(m_admin_quote.group(1))
            aq = parse_qs(parsed_req.query)
            version_no = None
            vn0 = aq.get("version", [None])[0]
            if vn0 is not None and str(vn0).strip() != "":
                try:
                    version_no = int(vn0)
                except (TypeError, ValueError):
                    version_no = None
            bundle = get_saved_quote_admin_bundle(qida, version_no=version_no)
            if not bundle:
                self.write_json({"error": "not_found"}, status=404)
                return
            self.write_json(deep_repair_strings(bundle))
            return

        m_files = re.match(r"^/admin-api/quotes/([^/]+)/files/?$", req_path)
        if m_files:
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            qid = unquote(m_files.group(1))
            rows = list_quote_files_for_quote(qid)
            self.write_json({"quote_id": qid, "files": rows})
            return

        path_only_dl = parsed_req.path
        m_dl = re.match(r"^/admin-api/quotes/files/([^/]+)/download/?$", path_only_dl)
        if m_dl:
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            fid = unquote(m_dl.group(1))
            rec = get_quote_file_record(fid)
            if not rec:
                self.write_json({"error": "not_found", "message": "文件不存在。"}, status=404)
                return
            fs_path = resolve_stored_file_path(str(rec.get("stored_path") or ""))
            if not fs_path:
                self.write_json({"error": "not_found", "message": "磁盘文件不可用。"}, status=404)
                return
            mime = str(rec.get("mime_type") or "application/octet-stream")
            name = str(rec.get("original_name") or "download.bin")
            self.write_file_attachment(fs_path, name, mime)
            return

        if req_path == "/admin/login":
            self.serve_static(STATIC_DIR / "admin" / "login.html")
            return

        if req_path.startswith("/admin"):
            if not verify_backend_admin_cookie(self.headers.get("Cookie")):
                self.send_response(302)
                self.send_header("Location", "/admin/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if req_path in ("/admin", "/admin/quotes"):
                self.serve_static(STATIC_DIR / "admin" / "index.html")
                return
            if req_path == "/admin/prices":
                self.serve_static(STATIC_DIR / "admin" / "prices.html")
                return
            self.send_response(302)
            self.send_header("Location", "/admin/quotes")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        static_rel = _static_relative_path(self.path)
        if static_rel:
            self.serve_static(STATIC_DIR / static_rel)
            return

        self.write_json({"error": "not found"}, status=404)

    def has_sheet_blob_in_payload(self, payload: dict) -> bool:
        us = payload.get("uploaded_sheet")
        if not isinstance(us, dict):
            return False
        if str(us.get("content_base64") or "").strip():
            return True
        if str(us.get("data") or "").strip() or str(us.get("content") or "").strip():
            return True
        return False

    def _apply_llm_suggested_processing_fee(
        self,
        payload: dict,
        llm_status: object,
        demand_parse_result: DemandParseResult | None,
    ) -> None:
        """表格已锁定加工费时不覆盖；否则采用模型返回的 suggested_processing_fee。"""
        if demand_parse_result is not None and demand_parse_result.quote_settings.get(
            "processing_fee_locked",
        ):
            return
        if not isinstance(llm_status, dict):
            return
        spf = llm_status.get("suggested_processing_fee")
        try:
            v = float(spf)
            if v > 0:
                cap = None
                if demand_parse_result is not None:
                    try:
                        cap = float(demand_parse_result.quote_settings.get("processing_fee_cap"))
                    except (TypeError, ValueError):
                        cap = None
                if cap is not None and cap > 0:
                    v = min(v, cap)
                payload["processing_fee"] = round(v, 2)
        except (TypeError, ValueError):
            pass

    def _apply_quote_output_gate(self, response: dict, payload: dict) -> None:
        sid = getattr(self, "_cookie_session_id", "") or ""
        manual = False
        if sid:
            row = GLOBAL_SESSION_STORE.get(sid)
            manual = bool(row and row.get("pricing_gate_confirmed"))
        apply_pricing_gate(response, payload, manual_confirmed=manual)

    def handle_quote_client_actions(self, payload: dict) -> bool:
        """UI 快捷操作（无表格上传）：试算升级为主报价等。"""
        if not isinstance(payload, dict):
            return False
        action = str(payload.get("client_action") or "").strip()
        if action == "promote_material_to_primary":
            return self._promote_material_to_primary(payload)
        if action != "promote_extra_to_primary":
            return False
        sid = self._cookie_session_id
        sc_raw = payload.get("session_context")
        sc = sc_raw if isinstance(sc_raw, dict) else {}
        qid = str(sc.get("currentQuoteId") or "").strip()
        try:
            n = int(float(payload.get("promote_quantity")))
        except (TypeError, ValueError):
            self.write_json(
                {"quote_ready": False, "assistant_message": "无效的数量。"},
                status=400,
            )
            return True
        if n < 1:
            self.write_json(
                {"quote_ready": False, "assistant_message": "数量须为正整数。"},
                status=400,
            )
            return True
        if not qid or not GLOBAL_SESSION_STORE.validate_quote_id(sid, qid):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": FOLLOW_UP_NO_SESSION_HINT,
                    "llm_status": get_kimi_status(),
                }
            )
            return True
        base = GLOBAL_SESSION_STORE.get_payload_for_quote(sid, qid)
        if not base or not isinstance(base.get("items"), list):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": FOLLOW_UP_NO_SESSION_HINT,
                    "llm_status": get_kimi_status(),
                }
            )
            return True
        if not has_effective_material_pricing(base.get("items")):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": "物料金额无效，无法升级为主报价。",
                    "llm_status": get_kimi_status(),
                }
            )
            return True
        llm_status = get_kimi_status()
        merged = copy.deepcopy(base)
        merged["quantities"] = [n]
        response = calculate_quote(merged)
        merge_quote_sales_from_payload(response, merged)
        self._apply_quote_output_gate(response, merged)
        response["quote_ready"] = True
        response["quote_id"] = str(uuid.uuid4())
        response["intent"] = "promote_to_primary"
        response["llm_status"] = llm_status
        if isinstance(llm_status, dict):
            summary = str(llm_status.pop("consultant_summary", "") or "").strip()
            if summary:
                response["consultant_summary"] = summary
        stored = GLOBAL_SESSION_STORE.get(sid) or {}
        fn = str(sc.get("fileName") or stored.get("file_name") or "")
        snap = copy.deepcopy(merged)
        snap.pop("uploaded_sheet", None)
        series_uid = resolve_quote_series_uid(sid, merged, response)
        if not _persist_quote_with_sales_user(
            self,
            series_uid=series_uid,
            response=response,
            payload=merged,
            sheet_fn=fn,
            uploaded_sheet=merged.get("uploaded_sheet") if isinstance(merged.get("uploaded_sheet"), dict) else None,
            user_message=str(payload.get("message_text") or payload.get("user_prompt") or payload.get("prompt") or ""),
        ):
            return
        _safe_sync_price_kb_from_quote(response)
        GLOBAL_SESSION_STORE.set_current_quote(
            sid, response["quote_id"], fn, snap, response, quote_series_uid=series_uid
        )
        _sync_agent_graph_quote_context(
            sid=sid,
            payload_snapshot=snap,
            quote_result=response,
            user_message=str(payload.get("message_text") or payload.get("user_prompt") or payload.get("prompt") or ""),
            local_intent=str(response.get("intent") or "promote_to_primary"),
        )
        self.write_json(response)
        return True

    def _promote_material_to_primary(self, payload: dict) -> bool:
        sid = self._cookie_session_id
        sc_raw = payload.get("session_context")
        sc = sc_raw if isinstance(sc_raw, dict) else {}
        qid = str(sc.get("currentQuoteId") or "").strip()
        trial_items = payload.get("trial_items")
        if not isinstance(trial_items, list) or not trial_items:
            self.write_json(
                {"quote_ready": False, "assistant_message": "缺少试算物料明细。"},
                status=400,
            )
            return True
        if not qid or not GLOBAL_SESSION_STORE.validate_quote_id(sid, qid):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": FOLLOW_UP_NO_SESSION_HINT,
                    "llm_status": get_kimi_status(),
                }
            )
            return True
        base = GLOBAL_SESSION_STORE.get_payload_for_quote(sid, qid)
        if not base or not isinstance(base.get("items"), list):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": FOLLOW_UP_NO_SESSION_HINT,
                    "llm_status": get_kimi_status(),
                }
            )
            return True
        if not has_effective_material_pricing(trial_items):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": "试算物料金额无效，无法升级为主报价。",
                    "llm_status": get_kimi_status(),
                }
            )
            return True
        llm_status = get_kimi_status()
        merged = copy.deepcopy(base)
        merged["items"] = copy.deepcopy(trial_items)
        merged["quantities"] = copy.deepcopy(base.get("quantities"))
        response = calculate_quote(merged)
        merge_quote_sales_from_payload(response, merged)
        self._apply_quote_output_gate(response, merged)
        response["quote_ready"] = True
        response["quote_id"] = str(uuid.uuid4())
        response["intent"] = "promote_material_to_primary"
        response["llm_status"] = llm_status
        if isinstance(llm_status, dict):
            summary = str(llm_status.pop("consultant_summary", "") or "").strip()
            if summary:
                response["consultant_summary"] = summary
        stored = GLOBAL_SESSION_STORE.get(sid) or {}
        fn = str(sc.get("fileName") or stored.get("file_name") or "")
        snap = copy.deepcopy(merged)
        snap.pop("uploaded_sheet", None)
        series_uid = resolve_quote_series_uid(sid, merged, response)
        if not _persist_quote_with_sales_user(
            self,
            series_uid=series_uid,
            response=response,
            payload=merged,
            sheet_fn=fn,
            uploaded_sheet=merged.get("uploaded_sheet") if isinstance(merged.get("uploaded_sheet"), dict) else None,
            user_message=str(payload.get("message_text") or payload.get("user_prompt") or payload.get("prompt") or ""),
        ):
            return
        _safe_sync_price_kb_from_quote(response)
        GLOBAL_SESSION_STORE.set_current_quote(
            sid, response["quote_id"], fn, snap, response, quote_series_uid=series_uid
        )
        _sync_agent_graph_quote_context(
            sid=sid,
            payload_snapshot=snap,
            quote_result=response,
            user_message=str(payload.get("message_text") or payload.get("user_prompt") or payload.get("prompt") or ""),
            local_intent=str(response.get("intent") or "promote_material_to_primary"),
        )
        self.write_json(response)
        return True

    def handle_session_intent_quote(self, payload: dict) -> bool:
        """无新表格上传时：处理追问/闲聊/对比；已写响应则返回 True。"""
        if not isinstance(payload, dict):
            return False
        if self.has_sheet_blob_in_payload(payload):
            return False
        if isinstance(payload.get("items"), list) and payload.get("items"):
            return False

        sid = self._cookie_session_id or self.ensure_session_id()
        user_text = str(payload.get("user_prompt") or payload.get("prompt") or "").strip()
        sc_raw = payload.get("session_context")
        sc = sc_raw if isinstance(sc_raw, dict) else {}
        qid = _resolve_active_quote_id_from_context(sid, sc)
        has_session_quote = bool(qid)
        intent = classify_intent(
            user_text,
            has_new_upload=False,
            has_session_quote=has_session_quote,
        )
        llm_status = get_kimi_status()

        if intent == "CHAT":
            from message_intent import looks_like_chat_only

            if looks_like_chat_only(user_text) and not looks_like_business_assistant(
                user_text, has_active_quote=has_session_quote
            ):
                self.write_json(
                    {
                        "quote_ready": False,
                        "assistant_message": CHAT_STUB_REPLY,
                        "intent": intent,
                        "reply_type": "clarify",
                        "llm_status": llm_status,
                    }
                )
                return True
            if _try_business_assistant_response(
                self,
                user_text,
                payload,
                has_active_quote=has_session_quote,
            ):
                return True
            qa = _qa_response_for_route(user_text, sid=sid)
            self.write_json(qa)
            return True
        if intent == "COMPARE":
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": COMPARE_STUB_REPLY,
                    "intent": intent,
                    "llm_status": llm_status,
                }
            )
            return True
        if intent == "NEW_QUOTE":
            return False
        if intent != "FOLLOW_UP":
            return False

        stored = GLOBAL_SESSION_STORE.get(sid) or {}
        fn = str(sc.get("fileName") or stored.get("file_name") or "")
        if not qid:
            if should_explain_quote_without_requote(user_text):
                st = dict(llm_status) if isinstance(llm_status, dict) else {}
                st.setdefault("agent", "langgraph_quote_agent")
                self.write_json(
                    {
                        "quote_ready": False,
                        "assistant_message": (
                            "我能解释报价误差和计算口径，但当前没有可引用的 active_quote（上一单报价）。"
                            "请先生成一次报价，或打开对应报价卡后再追问「为啥误差这么大」。"
                        ),
                        "intent": "FOLLOW_UP",
                        "llm_status": st,
                    }
                )
                return True
            mem_in = _agent_memory_get(sid)
            try:
                from quote_agent.graph import invoke_quote_agent

                response_payload = invoke_quote_agent(
                    sid=sid,
                    user_message=user_text,
                    session_context={**sc, "fileName": fn},
                    llm_status=llm_status if isinstance(llm_status, dict) else {},
                    memory=mem_in,
                    finalize_quote_persistence=finalize_quote_persistence,
                    resolve_quote_series_uid=resolve_quote_series_uid,
                    apply_output_gate=self._apply_quote_output_gate,
                    sync_agent_context=_sync_agent_graph_quote_context,
                    agent_memory_put=_agent_memory_put,
                )
            except ImportError:
                response_payload = {
                    "quote_ready": False,
                    "assistant_message": "未安装 LangGraph 依赖，请安装 langgraph / langchain-core。",
                    "intent": "AGENT_UNAVAILABLE",
                    "llm_status": llm_status,
                }
            self.write_json(response_payload)
            return True

        if not GLOBAL_SESSION_STORE.validate_quote_id(sid, qid):
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": (
                        "本次会话中的报价上下文已过期，请重新上传表格生成报价，"
                        "或在问题中 @ 历史报价文件名。"
                    ),
                    "intent": "FOLLOW_UP",
                    "llm_status": llm_status,
                }
            )
            return True

        last_res = GLOBAL_SESSION_STORE.get_last_quote_result(sid, qid) or {}
        if should_explain_quote_without_requote(user_text) and last_res.get("tiers"):
            sync = last_res.get("price_kb_sync") if isinstance(last_res.get("price_kb_sync"), dict) else None
            st = dict(llm_status) if isinstance(llm_status, dict) else {}
            st.setdefault("agent", "quote_explain_local")
            self.write_json(
                build_explain_response_payload(
                    last_res,
                    user_question=user_text,
                    price_kb_sync=sync,
                    llm_status=st,
                )
            )
            return True

        if is_dimension_follow_up_only(user_text):
            hint = build_dimension_hint_from_result(last_res)
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": hint,
                    "intent": "FOLLOW_UP",
                    "llm_status": llm_status,
                }
            )
            return True

        base = GLOBAL_SESSION_STORE.get_payload_for_quote(sid, qid)
        if not base or not isinstance(base.get("items"), list) or len(base.get("items") or []) == 0:
            self.write_json(
                {
                    "quote_ready": False,
                    "assistant_message": FOLLOW_UP_NO_SESSION_HINT,
                    "intent": "FOLLOW_UP",
                    "llm_status": llm_status,
                }
            )
            return True

        mem_in = _agent_memory_get(sid)
        try:
            from quote_agent.graph import invoke_quote_agent

            response_payload = invoke_quote_agent(
                sid=sid,
                user_message=user_text,
                session_context={**sc, "currentQuoteId": qid, "fileName": fn},
                llm_status=llm_status if isinstance(llm_status, dict) else {},
                memory=mem_in,
                finalize_quote_persistence=finalize_quote_persistence,
                resolve_quote_series_uid=resolve_quote_series_uid,
                apply_output_gate=self._apply_quote_output_gate,
                sync_agent_context=_sync_agent_graph_quote_context,
                agent_memory_put=_agent_memory_put,
            )
        except ImportError:
            response_payload = {
                "quote_ready": False,
                "assistant_message": "未安装 LangGraph 依赖，请安装 langgraph / langchain-core。",
                "intent": "AGENT_UNAVAILABLE",
                "llm_status": llm_status,
            }
        self.write_json(response_payload)
        return True

    def do_GET(self) -> None:
        self._request_started_at = time.time()
        self._request_id = self.headers.get("X-Request-ID") or _short_request_id()
        site = getattr(self.server, "_quote_site", "front")
        if site == "admin":
            if not self._admin_client_ip_allowed():
                self.write_json(
                    {"error": "forbidden", "message": "后台访问来源不在允许列表（QUOTE_ADMIN_ALLOW_IPS）。"},
                    status=403,
                )
                return
            parsed_req = urlparse(self.path)
            req_path = parsed_req.path.rstrip("/") or "/"
            self._admin_site_do_GET(parsed_req, req_path)
            return

        parsed_req = urlparse(self.path)
        front_path = parsed_req.path.rstrip("/") or "/"
        if front_path == "/" or front_path == "/index.html":
            self.serve_static(STATIC_DIR / "index.html")
            return
        if self.path == "/api/quote":
            self.write_json(
                {
                    "quote_ready": False,
                    "llm_status": get_kimi_status(),
                }
            )
            return
        if self.path == "/api/llm/status" or self.path.startswith("/api/llm/status?"):
            parsed_status = urlparse(self.path)
            qs_status = parse_qs(parsed_status.query)
            probe_raw = (qs_status.get("probe") or [""])[0].strip().lower()
            probe = probe_raw in {"1", "true", "yes", "on"}
            self.write_json(get_kimi_status(probe=probe))
            return
        if self.path == "/api/llm/health" or self.path.startswith("/api/llm/health?"):
            parsed_health = urlparse(self.path)
            qs_health = parse_qs(parsed_health.query)
            live_raw = (qs_health.get("live") or qs_health.get("probe") or ["1"])[0].strip().lower()
            live_probe = live_raw not in {"0", "false", "no", "off"}
            self.write_json(build_llm_health_report(live_probe=live_probe))
            return
        if self.path == "/api/quote-sheet/terms":
            self.write_json(get_quote_sheet_terms_public())
            return
        if self.path == "/api/quote-sheet/payment-accounts":
            self.write_json(get_company_payment_accounts_public())
            return
        if self.path.startswith("/api/quote-sheet/payment-accounts/search"):
            parsed_pay = urlparse(self.path)
            qs_pay = parse_qs(parsed_pay.query)
            query = (qs_pay.get("q") or qs_pay.get("query") or [""])[0]
            limit_raw = (qs_pay.get("limit") or ["12"])[0]
            try:
                limit = max(1, min(100, int(str(limit_raw).strip())))
            except (TypeError, ValueError):
                limit = 12
            self.write_json(search_company_accounts(query, limit=limit))
            return
        if self.path == "/api/auth/status" or self.path.startswith("/api/auth/status?"):
            sales_uid, sales_name, ok = _resolve_front_sales_identity(self)
            self.write_json(
                auth_status_payload(
                    sales_user_id=sales_uid,
                    sales_user_name=sales_name,
                    authenticated=ok and bool(sales_uid),
                )
            )
            return
        if self.path == "/api/auth/wecom/login" or self.path.startswith("/api/auth/wecom/login?"):
            if not wecom_enabled() or get_wecom_config() is None:
                self.write_json({"error": "wecom_disabled", "message": "企业微信登录未启用。"}, status=404)
                return
            parsed_login = urlparse(self.path)
            qs_login = parse_qs(parsed_login.query)
            state = (qs_login.get("state") or [""])[0].strip() or uuid.uuid4().hex
            try:
                url = build_oauth_authorize_url(state=state)
            except RuntimeError as exc:
                self.write_json({"error": "wecom_misconfigured", "message": str(exc)}, status=500)
                return
            self.send_redirect(url)
            return

        path_only = parsed_req.path.split("?", 1)[0].rstrip("/") or "/"
        if path_only == "/api/auth/wecom/callback":
            if not wecom_enabled() or get_wecom_config() is None:
                self.write_json({"error": "wecom_disabled", "message": "企业微信登录未启用。"}, status=404)
                return
            qs_cb = parse_qs(parsed_req.query)
            oauth_err = (qs_cb.get("error") or [""])[0].strip()
            if oauth_err:
                _redirect_wecom_oauth_error(
                    self,
                    error_code="wecom_oauth_denied",
                    message=f"企业微信授权被拒绝：{oauth_err}",
                )
                return
            code = (qs_cb.get("code") or [""])[0].strip()
            if not code:
                _redirect_wecom_oauth_error(
                    self,
                    error_code="invalid_request",
                    message="缺少 OAuth code，请从企业微信重新进入应用。",
                )
                return
            try:
                sales_uid, sales_name = exchange_code_for_profile(code)
            except (ValueError, RuntimeError) as exc:
                _redirect_wecom_oauth_error(
                    self,
                    error_code="wecom_oauth_failed",
                    message=str(exc),
                )
                return
            try:
                _set_front_sales_cookies(self, sales_uid, sales_name)
                token = issue_sales_session_token(sales_uid, sales_name)
            except RuntimeError as exc:
                _redirect_wecom_oauth_error(
                    self,
                    error_code="sales_secret_missing",
                    message=str(exc),
                )
                return
            cfg = get_wecom_config()
            target = cfg.public_base_url if cfg else "/"
            logout_headers = [
                set_sales_session_cookie_header(token),
                ("Set-Cookie", clear_sales_user_cookie_header_value()),
                ("Set-Cookie", clear_sales_user_name_cookie_header_value()),
            ]
            self.send_redirect(target, extra_headers=logout_headers)
            return
        if path_only == "/api/auth/wecom/logout":
            self.send_redirect(
                "/",
                extra_headers=[
                    clear_sales_session_cookie_header(),
                    ("Set-Cookie", clear_sales_user_cookie_header_value()),
                    ("Set-Cookie", clear_sales_user_name_cookie_header_value()),
                ],
            )
            return

        if self.path == "/api/my/quotes" or self.path.startswith("/api/my/quotes?"):
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            qs_my = parse_qs(parsed_req.query)
            status_raw = (qs_my.get("status") or [""])[0].strip().lower()
            items = list_my_quotes_for_sales_user(
                sales_uid,
                status_filter=status_raw or None,
            )
            self.write_json({"items": items, "sales_user_id": sales_uid})
            return
        if path_only == "/api/my/admin-updates":
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            items = list_my_admin_updates_for_sales_user(sales_uid)
            unread = count_unread_admin_updates_for_sales_user(sales_uid)
            self.write_json({"items": items, "unread_count": unread, "sales_user_id": sales_uid})
            return
        m_my_quote_detail = re.match(r"^/api/my/quotes/([^/]+)/?$", path_only)
        if m_my_quote_detail:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_my_quote_detail.group(1))
            detail = get_my_quote_session_detail(series_uid, sales_uid)
            if detail is None:
                self.write_json({"error": "not_found", "message": "报价不存在或无权查看。"}, status=404)
                return
            self.write_json(detail)
            return
        m_quote_sheet_prefill = re.match(
            r"^/api/my/quotes/([^/]+)/quote-sheet-prefill/?$",
            path_only,
        )
        if m_quote_sheet_prefill:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_quote_sheet_prefill.group(1))
            qs_pf = parse_qs(parsed_req.query)
            source = (qs_pf.get("source") or ["record"])[0].strip().lower() or "record"
            payload = build_quote_sheet_prefill_payload(
                series_uid,
                sales_uid,
                source=source,
            )
            if payload is None:
                self.write_json(
                    {"ok": False, "error": "not_found", "message": "报价不存在或无权查看。"},
                    status=404,
                )
                return
            self.write_json(payload)
            return
        m_quote_sheet_meta = re.match(
            r"^/api/my/quotes/([^/]+)/quote-sheet-meta/?$",
            path_only,
        )
        if m_quote_sheet_meta:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_quote_sheet_meta.group(1))
            if self.command == "POST":
                body = self.read_json()
                meta_in = body.get("meta") if isinstance(body, dict) else None
                if not isinstance(meta_in, dict):
                    self.write_json(
                        {"ok": False, "error": "invalid_request", "message": "缺少 meta 对象。"},
                        status=400,
                    )
                    return
                qnm = body.get("quote_no_manual") if isinstance(body, dict) else None
                manual = qnm if isinstance(qnm, bool) else None
                result = save_quote_sheet_meta(
                    series_uid,
                    sales_uid,
                    meta_in,
                    quote_no_manual=manual,
                )
                if not result.get("ok"):
                    st = 404 if result.get("error") == "not_found" else 400
                    self.write_json(result, status=st)
                    return
                self.write_json(result)
                return
            self.write_json(
                {"ok": False, "error": "method_not_allowed", "message": "请使用 POST 保存。"},
                status=405,
            )
            return
        m_corr_dl = re.match(r"^/api/my/quotes/([^/]+)/correction-sheet/download/?$", path_only)
        if m_corr_dl:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_corr_dl.group(1))
            rec = get_admin_correction_sheet_for_sales(series_uid, sales_uid)
            if not rec:
                self.write_json({"error": "not_found", "message": "修正版表格不存在或无权下载。"}, status=404)
                return
            fs_path = resolve_stored_file_path(str(rec.get("stored_path") or ""))
            if not fs_path:
                self.write_json({"error": "not_found", "message": "磁盘文件不可用。"}, status=404)
                return
            mime = str(rec.get("mime_type") or "application/octet-stream")
            name = str(rec.get("original_name") or "correction-sheet.bin")
            self.write_file_attachment(fs_path, name, mime)
            return
        m_calc_dl = re.match(r"^/api/my/quotes/([^/]+)/calculated-sheet/download/?$", path_only)
        if m_calc_dl:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_calc_dl.group(1))
            rec = get_admin_calculated_sheet_for_sales(series_uid, sales_uid)
            if not rec:
                self.write_json({"error": "not_found", "message": "自算表格不存在或无权下载。"}, status=404)
                return
            fs_path = resolve_stored_file_path(str(rec.get("stored_path") or ""))
            if not fs_path:
                self.write_json({"error": "not_found", "message": "磁盘文件不可用。"}, status=404)
                return
            mime = str(rec.get("mime_type") or "application/octet-stream")
            name = str(rec.get("original_name") or "calculated-sheet.bin")
            self.write_file_attachment(fs_path, name, mime)
            return
        m_sales_dl = re.match(r"^/api/my/quotes/([^/]+)/sales-sheet/download/?$", path_only)
        if m_sales_dl:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_sales_dl.group(1))
            rec = get_sales_original_sheet_for_sales(series_uid, sales_uid)
            if not rec:
                self.write_json({"error": "not_found", "message": "原始表格不存在或无权下载。"}, status=404)
                return
            fs_path = resolve_stored_file_path(str(rec.get("stored_path") or ""))
            if not fs_path:
                self.write_json({"error": "not_found", "message": "磁盘文件不可用。"}, status=404)
                return
            mime = str(rec.get("mime_type") or "application/octet-stream")
            name = str(rec.get("original_name") or "sales-sheet.bin")
            self.write_file_attachment(fs_path, name, mime)
            return

        if self._front_is_blocked_request(path_only):
            self.write_json({"error": "not found"}, status=404)
            return

        m_quote_approval_get = re.match(r"^/api/quotes/([^/]+)/approval/?$", path_only)
        if m_quote_approval_get:
            lookup_id = unquote(m_quote_approval_get.group(1))
            auth = _require_front_sales_auth(self)
            if auth is None:
                _json_log(
                    "approval_lookup_auth_failed",
                    request_id=getattr(self, "_request_id", ""),
                    lookup_id=lookup_id,
                    path=path_only,
                )
                return
            sales_uid, _ = auth
            try:
                snap = get_saved_quote_approval_for_sales_user(lookup_id, sales_uid)
            except Exception as exc:
                _json_log(
                    "approval_lookup_failed",
                    request_id=getattr(self, "_request_id", ""),
                    lookup_id=lookup_id,
                    sales_user_id=sales_uid,
                    error=str(exc),
                )
                self.write_json(
                    {"error": "approval_lookup_failed", "message": str(exc)},
                    status=500,
                )
                return
            if snap is None:
                _json_log(
                    "approval_lookup_not_found",
                    request_id=getattr(self, "_request_id", ""),
                    lookup_id=lookup_id,
                    sales_user_id=sales_uid,
                )
                self.write_json(
                    {"error": "not_found", "message": "报价不存在或无权查看审批状态。"},
                    status=404,
                )
                return
            _json_log(
                "approval_lookup_ok",
                request_id=getattr(self, "_request_id", ""),
                lookup_id=lookup_id,
                sales_user_id=sales_uid,
                approval_status=snap.get("approval_status"),
            )
            self.write_json(snap)
            return

        static_rel = _static_relative_path(self.path)
        if static_rel:
            self.serve_static(STATIC_DIR / static_rel)
            return
        self.write_json({"error": "not found"}, status=404)

    def _admin_site_do_POST(self) -> None:
        path = _canonical_http_path_only(self.path)
        if path == "/admin-api/login":
            payload = self.read_json()
            role = authenticate(payload.get("username"), payload.get("password"))
            if role is None:
                self.write_json({"ok": False, "error": "invalid_credentials"}, status=401)
                return
            if role != ROLE_ADMIN:
                self.write_json(
                    {
                        "ok": False,
                        "error": "forbidden",
                        "message": "后台仅允许管理员账号登录。",
                    },
                    status=403,
                )
                return
            tok = issue_session_token(role)
            self.write_json_response(
                {"ok": True, "role": role}, extra_headers=set_login_cookie_headers(tok)
            )
            return
        if path == "/admin-api/logout":
            self.write_json_response({"ok": True}, extra_headers=[set_logout_cookie_header()])
            return
        m_quote_approve = re.match(r"^/admin-api/quotes/([^/]+)/approve/?$", path)
        if m_quote_approve or path == "/admin-api/quotes/approve":
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if body is None:
                body = {}
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            version_no = body.get("version_no")
            try:
                version_no_i = int(version_no) if version_no not in (None, "") else None
            except (TypeError, ValueError):
                self.write_json({"error": "invalid_request", "message": "版本号无效。"}, status=400)
                return
            quote_uid = ""
            if m_quote_approve:
                quote_uid = unquote(m_quote_approve.group(1))
            else:
                quote_uid = str(body.get("quote_uid") or body.get("quote_id") or "").strip()
            if not quote_uid:
                self.write_json({"error": "invalid_request", "message": "缺少报价 UID。"}, status=400)
                return
            note_raw = body.get("approval_note")
            approval_note = (
                str(note_raw).strip() if note_raw is not None and str(note_raw).strip() != "" else None
            )
            try:
                from quote_approval import resolve_reviewer_name_from_request

                reviewer_name = resolve_reviewer_name_from_request(body)
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            try:
                result = approve_saved_quote(
                    quote_uid,
                    version_no=version_no_i,
                    approved_by=reviewer_name,
                    approval_note=approval_note,
                )
            except ValueError as exc:
                _json_log(
                    "approval_update_invalid",
                    request_id=getattr(self, "_request_id", ""),
                    quote_uid=quote_uid,
                    approval_status="approved",
                    version_no=version_no_i,
                    error=str(exc),
                )
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                _json_log(
                    "approval_update_failed",
                    request_id=getattr(self, "_request_id", ""),
                    quote_uid=quote_uid,
                    approval_status="approved",
                    version_no=version_no_i,
                    error=str(exc),
                )
                self.write_json({"error": "approval_failed", "message": str(exc)}, status=500)
                return
            _json_log(
                "approval_update_ok",
                request_id=getattr(self, "_request_id", ""),
                quote_uid=quote_uid,
                approval_status=result.get("approval_status"),
                approved_version_no=result.get("approved_version_no"),
                approved_calc_quote_id=result.get("approved_calc_quote_id"),
            )
            self.write_json(result)
            return
        m_quote_approval = re.match(r"^/admin-api/quotes/([^/]+)/approval/?$", path)
        if m_quote_approval:
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            raw_status = body.get("approval_status")
            if raw_status is None or str(raw_status).strip() == "":
                self.write_json(
                    {
                        "error": "invalid_request",
                        "message": "缺少 approval_status（pending / approved / rejected）。",
                    },
                    status=400,
                )
                return
            version_no = body.get("version_no")
            try:
                version_no_i = int(version_no) if version_no not in (None, "") else None
            except (TypeError, ValueError):
                self.write_json({"error": "invalid_request", "message": "版本号无效。"}, status=400)
                return
            quote_uid = unquote(m_quote_approval.group(1))
            note_raw = body.get("approval_note")
            approval_note = str(note_raw) if note_raw is not None else ""
            try:
                from quote_approval import resolve_reviewer_name_from_request

                reviewer_name = resolve_reviewer_name_from_request(body)
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            try:
                result = update_saved_quote_approval(
                    quote_uid,
                    approval_status=str(raw_status),
                    approval_note=approval_note,
                    version_no=version_no_i,
                    reviewed_by=reviewer_name,
                )
            except ValueError as exc:
                _json_log(
                    "approval_update_invalid",
                    request_id=getattr(self, "_request_id", ""),
                    quote_uid=quote_uid,
                    approval_status=str(raw_status),
                    version_no=version_no_i,
                    error=str(exc),
                )
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                _json_log(
                    "approval_update_failed",
                    request_id=getattr(self, "_request_id", ""),
                    quote_uid=quote_uid,
                    approval_status=str(raw_status),
                    version_no=version_no_i,
                    error=str(exc),
                )
                self.write_json({"error": "approval_failed", "message": str(exc)}, status=500)
                return
            _json_log(
                "approval_update_ok",
                request_id=getattr(self, "_request_id", ""),
                quote_uid=quote_uid,
                approval_status=result.get("approval_status"),
                approved_version_no=result.get("approved_version_no"),
                approved_calc_quote_id=result.get("approved_calc_quote_id"),
            )
            self.write_json(result)
            return
        m_bom_edit = re.match(r"^/admin-api/quotes/([^/]+)/bom-edit/?$", path)
        if m_bom_edit:
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            quote_uid = unquote(m_bom_edit.group(1))
            from admin_bom_recalc import admin_recalc_and_save_bom

            try:
                actor = str(
                    body.get("reviewed_by") or self.headers.get("X-Admin-User") or "admin"
                ).strip()
            except Exception:
                actor = "admin"
            result = admin_recalc_and_save_bom(quote_uid, body, admin_actor=actor or "admin")
            if not result.get("ok"):
                err = str(result.get("error") or "")
                status = 404 if err == "not_found" else 400
                self.write_json(result, status=status)
                return
            self.write_json(result)
            return
        m_feedback = re.match(r"^/admin-api/quotes/([^/]+)/feedback/?$", path)
        if m_feedback:
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            quote_uid = unquote(m_feedback.group(1))
            try:
                actor = str(body.get("reviewed_by") or self.headers.get("X-Admin-User") or "admin").strip()
            except Exception:
                actor = "admin"
            note_raw = body.get("correction_note")
            if note_raw is None:
                note_raw = body.get("admin_correction_note")
            correction_note = str(note_raw) if note_raw is not None else ""
            problem_types_raw = body.get("correction_problem_types")
            if problem_types_raw is None:
                problem_types_raw = body.get("problem_types")
            try:
                result = save_admin_quote_feedback(
                    quote_uid,
                    correction_note=correction_note,
                    correction_problem_types=problem_types_raw,
                    reviewed_by=actor or "admin",
                )
            except ValueError as exc:
                msg = str(exc)
                if msg == "not_found":
                    self.write_json(
                        {"error": "not_found", "message": _ADMIN_QUOTE_NOT_FOUND_MSG},
                        status=404,
                    )
                    return
                self.write_json({"error": "invalid_request", "message": msg}, status=400)
                return
            self.write_json(result)
            return
        m_corr_sheet = re.match(r"^/admin-api/quotes/([^/]+)/correction-sheet/?$", path)
        if m_corr_sheet:
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            quote_uid = unquote(m_corr_sheet.group(1))
            uploaded = body.get("uploaded_sheet")
            if not isinstance(uploaded, dict):
                uploaded = {
                    "name": body.get("name") or body.get("original_name") or "",
                    "content_base64": body.get("content_base64") or "",
                }
            replace_confirmed = str(body.get("replace_confirmed") or body.get("confirm_replace") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            try:
                actor = str(body.get("uploaded_by") or self.headers.get("X-Admin-User") or "admin").strip()
            except Exception:
                actor = "admin"
            try:
                result = persist_admin_correction_sheet(
                    quote_uid,
                    uploaded,
                    uploaded_by=actor or "admin",
                    replace_confirmed=replace_confirmed,
                )
            except ValueError as exc:
                msg = str(exc)
                if msg == "not_found":
                    self.write_json(
                        {"error": "not_found", "message": _ADMIN_QUOTE_NOT_FOUND_MSG},
                        status=404,
                    )
                    return
                if msg == "replace_confirm_required":
                    self.write_json(
                        {
                            "error": "replace_confirm_required",
                            "message": "已存在管理员修正版表格，替换前请确认。",
                        },
                        status=409,
                    )
                    return
                self.write_json({"error": "invalid_request", "message": msg}, status=400)
                return
            self.write_json(result)
            return
        m_calc_sheet = re.match(r"^/admin-api/quotes/([^/]+)/calculated-sheet/?$", path)
        if m_calc_sheet:
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            quote_uid = unquote(m_calc_sheet.group(1))
            uploaded = body.get("uploaded_sheet")
            if not isinstance(uploaded, dict):
                uploaded = {
                    "name": body.get("name") or body.get("original_name") or "",
                    "content_base64": body.get("content_base64") or "",
                }
            replace_confirmed = str(body.get("replace_confirmed") or body.get("confirm_replace") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            try:
                actor = str(body.get("uploaded_by") or self.headers.get("X-Admin-User") or "admin").strip()
            except Exception:
                actor = "admin"
            try:
                result = persist_admin_calculated_sheet(
                    quote_uid,
                    uploaded,
                    uploaded_by=actor or "admin",
                    replace_confirmed=replace_confirmed,
                )
            except ValueError as exc:
                msg = str(exc)
                if msg == "not_found":
                    self.write_json(
                        {"error": "not_found", "message": _ADMIN_QUOTE_NOT_FOUND_MSG},
                        status=404,
                    )
                    return
                if msg == "replace_confirm_required":
                    self.write_json(
                        {
                            "error": "replace_confirm_required",
                            "message": "已存在管理员自算表格，替换前请确认。",
                        },
                        status=409,
                    )
                    return
                self.write_json({"error": "invalid_request", "message": msg}, status=400)
                return
            self.write_json(result)
            return
        if path in _ADMIN_QUOTES_BATCH_DELETE_PATHS:
            if not self.require_admin_json_api():
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            mode = str(body.get("mode") or "by_ids").strip().lower().replace("-", "_")
            if mode in ("filtered_all", "filter_all", "all_matching"):
                if str(body.get("confirm") or "").strip() != "DELETE":
                    self.write_json(
                        {
                            "error": "confirm_required",
                            "message": "批量按筛选删除须传 confirm 字段，值为 DELETE。",
                        },
                        status=400,
                    )
                    return
                search_q = str(body.get("q") or body.get("search_q") or "").strip() or None
                date_from = str(body.get("from") or body.get("date_from") or "").strip()[:10] or None
                date_to = str(body.get("to") or body.get("date_to") or "").strip()[:10] or None
                version_min = None
                vmin_raw = body.get("version_min")
                if vmin_raw is not None and str(vmin_raw).strip() != "":
                    try:
                        version_min = int(vmin_raw)
                    except (TypeError, ValueError):
                        version_min = None
                st = str(body.get("status") or "").strip().lower()
                status_f = st if st in ("risk", "warn", "normal") else None
                deleted, failed = admin_delete_all_matching_list_filters(
                    search_q=search_q,
                    date_from=date_from,
                    date_to=date_to,
                    version_min=version_min,
                    status=status_f,
                )
                self.write_json(
                    {
                        "ok": True,
                        "deleted": deleted,
                        "failed_count": len(failed),
                        "failed_sample": failed[:50],
                    }
                )
                return
            # by_ids (default)
            raw_ids = body.get("quote_ids")
            out = admin_delete_quotes_by_ids(raw_ids if isinstance(raw_ids, list) else [])
            self.write_json({"ok": True, **out})
            return
        if path == "/admin-api/prices":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            try:
                result = upsert_price_entry(body)
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                self.write_json({"error": "price_update_failed", "message": str(exc)}, status=500)
                return
            self.write_json(result)
            return
        if path == "/admin-api/price-exceptions/approve":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            try:
                result = approve_price_exception(str(body.get("exception_id") or body.get("row_id") or ""), body)
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                self.write_json({"error": "price_exception_approve_failed", "message": str(exc)}, status=500)
                return
            self.write_json(result)
            return
        if path == "/admin-api/price-exceptions/exclude":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            try:
                result = exclude_price_exception(
                    str(body.get("exception_id") or body.get("row_id") or ""),
                    updated_by=str(body.get("updated_by") or "admin"),
                    note=str(body.get("note") or "").strip(),
                )
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            self.write_json(result)
            return
        if path == "/admin-api/price-exceptions/delete":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            try:
                result = delete_price_exception(
                    str(body.get("exception_id") or body.get("row_id") or ""),
                    updated_by=str(body.get("updated_by") or "admin"),
                )
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            self.write_json(result)
            return
        if path == "/admin-api/price-exceptions/delete-batch":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            raw_ids = body.get("exception_ids") or body.get("ids") or []
            if not isinstance(raw_ids, list):
                self.write_json({"error": "invalid_request", "message": "exception_ids 必须是数组。"}, status=400)
                return
            try:
                result = delete_price_exceptions_bulk(
                    [str(x) for x in raw_ids],
                    updated_by=str(body.get("updated_by") or "admin"),
                )
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            self.write_json(result)
            return
        if path == "/admin-api/prices/import":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            try:
                result = import_price_kb_workbook(
                    filename=str(body.get("filename") or ""),
                    content_base64=str(body.get("content_base64") or ""),
                    updated_by=str(body.get("updated_by") or "admin"),
                )
            except ValueError as exc:
                self.write_json({"error": "invalid_request", "message": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                self.write_json({"error": "import_failed", "message": str(exc)}, status=500)
                return
            self.write_json(result)
            return
        if path == "/admin-api/prices/delete":
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            row_id = str(body.get("row_id") or "").strip()
            if not row_id:
                self.write_json({"error": "invalid_request", "message": "缺少 row_id。"}, status=400)
                return
            updated_by = str(body.get("updated_by") or "admin").strip() or "admin"
            _handle_admin_price_delete(
                row_id,
                updated_by=updated_by,
                write_json=self.write_json,
                name=str(body.get("name") or "").strip(),
                spec=str(body.get("spec") or "").strip(),
                price=str(body.get("price") or body.get("unit_price") or "").strip(),
            )
            return
        self._discard_request_body()
        self.write_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        self._request_started_at = time.time()
        self._request_id = self.headers.get("X-Request-ID") or _short_request_id()
        site = getattr(self.server, "_quote_site", "front")
        if site == "admin":
            if not self._admin_client_ip_allowed():
                self.write_json(
                    {"error": "forbidden", "message": "后台访问来源不在允许列表（QUOTE_ADMIN_ALLOW_IPS）。"},
                    status=403,
                )
                return
            self._admin_site_do_POST()
            return

        path_only = _canonical_http_path_only(self.path)
        if self._front_post_reject_blocked_path(path_only):
            return

        if path_only == "/api/my/quotes/batch-delete":
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            raw_uids = body.get("quote_uids")
            if not isinstance(raw_uids, list):
                self.write_json(
                    {"error": "invalid_request", "message": "quote_uids 必须为数组。"},
                    status=400,
                )
                return
            try:
                result = batch_hide_quotes_for_sales_user(sales_uid, raw_uids)
            except ValueError as exc:
                msg = str(exc)
                if msg == "auth_required":
                    self.write_json({"error": "auth_required", "message": "请先登录。"}, status=401)
                    return
                if msg == "empty_quote_uids":
                    self.write_json(
                        {"error": "invalid_request", "message": "请至少选择一条报价记录。"},
                        status=400,
                    )
                    return
                self.write_json({"error": "invalid_request", "message": msg}, status=400)
                return
            self.write_json(result)
            return

        m_admin_viewed = re.match(r"^/api/my/quotes/([^/]+)/admin-update/viewed/?$", path_only)
        if m_admin_viewed:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_admin_viewed.group(1))
            result = mark_sales_admin_update_viewed(series_uid, sales_uid)
            if result is None:
                self.write_json({"error": "not_found", "message": "报价不存在或无权查看。"}, status=404)
                return
            self.write_json(result)
            return

        m_admin_handled = re.match(r"^/api/my/quotes/([^/]+)/admin-update/handled/?$", path_only)
        if m_admin_handled:
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, _ = auth
            series_uid = unquote(m_admin_handled.group(1))
            result = mark_sales_admin_update_handled(series_uid, sales_uid)
            if result is None:
                self.write_json({"error": "not_found", "message": "报价不存在或无权操作。"}, status=404)
                return
            self.write_json(result)
            return

        if self.path == "/api/session/pricing-gate/confirm":
            self._cookie_session_id = self.ensure_session_id()
            sid = self._cookie_session_id
            GLOBAL_SESSION_STORE.set_pricing_gate_confirmed(sid, True)
            row = GLOBAL_SESSION_STORE.get(sid)
            last = row.get("last_quote_result") if row else None
            if not isinstance(last, dict) or not last:
                self.write_json({"ok": False, "error": "no_active_quote"}, status=400)
                return
            result = copy.deepcopy(last)
            payload_snap = copy.deepcopy(row.get("payload_snapshot") or {})
            apply_pricing_gate(result, payload_snap, manual_confirmed=True, confirmed_by="session:user_confirm")
            GLOBAL_SESSION_STORE.replace_last_quote_result(sid, result)
            self.write_json({"ok": True, "quote": result})
            return

        if self.path == "/api/session/structure-checklist/patch":
            self._cookie_session_id = self.ensure_session_id()
            sid = self._cookie_session_id
            body = self.read_json()
            if not isinstance(body, dict):
                self.write_json({"ok": False, "error": "invalid_request"}, status=400)
                return
            structure_id = str(body.get("structure_id") or "").strip()
            user_status = str(body.get("user_status") or "").strip()
            user_note = str(body.get("user_note") or "").strip()
            if not structure_id or not user_status:
                self.write_json({"ok": False, "error": "missing_fields"}, status=400)
                return
            row = GLOBAL_SESSION_STORE.get(sid)
            last = row.get("last_quote_result") if row else None
            if not isinstance(last, dict) or not last:
                self.write_json({"ok": False, "error": "no_active_quote"}, status=400)
                return
            result = copy.deepcopy(last)
            payload_snap = copy.deepcopy(row.get("payload_snapshot") or {})
            checklist = result.get("structure_checklist")
            if not isinstance(checklist, dict):
                checklist = payload_snap.get("structure_checklist")
            if not isinstance(checklist, dict) or not checklist.get("is_bag_product"):
                self.write_json({"ok": False, "error": "no_structure_checklist"}, status=400)
                return
            try:
                updated = patch_structure_checklist_item(
                    checklist,
                    structure_id=structure_id,
                    user_status=user_status,
                    user_note=user_note,
                )
            except ValueError as exc:
                self.write_json({"ok": False, "error": str(exc)}, status=400)
                return
            payload_snap["structure_checklist"] = copy.deepcopy(updated)
            payload_snap["structure_checklist_user_dirty"] = True
            manual = bool(row and row.get("pricing_gate_confirmed"))
            apply_pricing_gate(result, payload_snap, manual_confirmed=manual)
            result["structure_checklist"] = updated
            result["structure_items"] = updated.get("items") or []
            result["structure_checklist_recalc_hint"] = (
                "结构清单已变更，请重新生成报价或重新计算后再对外使用。"
            )
            GLOBAL_SESSION_STORE.update_payload_snapshot(sid, payload_snap)
            GLOBAL_SESSION_STORE.replace_last_quote_result(sid, result)
            self.write_json({"ok": True, "quote": result, "recalc_hint": result["structure_checklist_recalc_hint"]})
            return

        if self.path == "/api/quote/messages":
            payload = self.read_json()
            if not isinstance(payload, dict):
                self.write_json({"error": "invalid_request", "message": "JSON 对象。"}, status=400)
                return
            self._cookie_session_id = self.ensure_session_id()
            auth = _require_front_sales_auth(self)
            if auth is None:
                return
            sales_uid, sales_name = auth
            series_uid = str(payload.get("quote_series_uid") or "").strip()
            if not series_uid:
                self.write_json({"error": "invalid_request", "message": "缺少 quote_series_uid。"}, status=400)
                return
            if not sales_user_can_access_quote(series_uid, sales_uid):
                self.write_json({"error": "forbidden", "message": "无权写入该报价会话。"}, status=403)
                return
            raw_msgs = payload.get("messages")
            if not isinstance(raw_msgs, list):
                self.write_json({"error": "invalid_request", "message": "messages 须为数组。"}, status=400)
                return
            saved = upsert_quote_chat_messages(
                series_uid,
                raw_msgs,
                sales_user_id=sales_uid,
                sales_user_name=sales_name,
            )
            self.write_json({"ok": True, "saved": saved, "quote_series_uid": series_uid})
            return

        if self.path == "/api/agent-turn":
            payload = self.read_json()
            self._cookie_session_id = self.ensure_session_id()
            sid = self._cookie_session_id

            if isinstance(payload.get("reset"), bool) and payload.get("reset"):
                with _AGENT_GRAPH_LOCK:
                    _AGENT_GRAPH_BY_SID.pop(sid, None)
                self.write_json({"ok": True, "reset": True})
                return

            try:
                from quotation_agent import empty_quotation_state, invoke_turn
            except ImportError as exc:
                self.write_json(
                    {
                        "ok": False,
                        "error": "agent_unavailable",
                        "message": "未安装 LangGraph 依赖：pip install langgraph langchain-core",
                        "detail": str(exc),
                    },
                    status=503,
                )
                return

            msg = str(payload.get("message") or payload.get("user_message") or "").strip()
            imgs_raw = payload.get("images")
            imgs, img_err = _normalize_agent_turn_images(imgs_raw)
            if img_err:
                self.write_json(
                    {"ok": False, "error": "invalid_images", "message": img_err},
                    status=400,
                )
                return
            if not msg and not imgs:
                self.write_json(
                    {
                        "ok": False,
                        "error": "invalid_request",
                        "message": "请至少提供 message 或 images。",
                    },
                    status=400,
                )
                return

            prev = _agent_graph_state_get(sid)
            state_in = empty_quotation_state() if prev is None else prev
            user_line = msg if msg else "（用户仅上传图片）"
            try:
                state_out = invoke_turn(
                    state_in,
                    user_message=user_line,
                    images_base64=imgs if imgs else None,
                )
            except ImportError as exc:
                self.write_json(
                    {
                        "ok": False,
                        "error": "agent_unavailable",
                        "message": str(exc),
                    },
                    status=503,
                )
                return

            _agent_graph_state_put(sid, state_out)
            self.write_json(
                {
                    "ok": True,
                    "reply": state_out.get("assistant_reply") or "",
                    "last_intent": state_out.get("last_intent"),
                    "parameters": state_out.get("parameters"),
                    "calculation_result": state_out.get("calculation_result"),
                    "chat_history": state_out.get("chat_history"),
                    "ran_calculator_this_turn": state_out.get("ran_calculator_this_turn"),
                    "vision_analysis_text": state_out.get("vision_analysis_text"),
                    "extracted_data": state_out.get("extracted_data"),
                    "final_reply": state_out.get("final_reply") or state_out.get("assistant_reply") or "",
                }
            )
            return

        if self.path == "/api/sheet/preview":
            payload = self.read_json()
            uploaded_sheet = payload.get("uploaded_sheet") if isinstance(payload, dict) else None
            if not isinstance(uploaded_sheet, dict):
                self.write_json(
                    {"error": "invalid_request", "message": "缺少 uploaded_sheet 数据。"},
                    status=400,
                )
                return
            try:
                parsed = parse_sheet_items_from_payload(uploaded_sheet)
            except SheetParseError as error:
                self.write_json(
                    {"error": "sheet_parse_failed", "message": str(error)},
                    status=400,
                )
                return
            self.write_json(parsed)
            return
        if self.path == "/api/quote-sheet/translate-en":
            payload = self.read_json()
            bundle = payload.get("bundle") if isinstance(payload, dict) else None
            if not isinstance(bundle, dict):
                self.write_json(
                    {"error": "invalid_request", "message": "缺少 bundle（JSON 对象）。"},
                    status=400,
                )
                return
            translated = translate_quote_sheet_fields(bundle)
            terms = get_quote_sheet_terms_public()
            labels = terms.get("labels") if isinstance(terms.get("labels"), dict) else {}
            fixed = terms.get("fixed") if isinstance(terms.get("fixed"), dict) else {}
            out = dict(translated)
            out["labels"] = labels
            out["fixed"] = fixed
            self.write_json(out)
            return
        if self.path == "/api/quote-sheet/terms/reload":
            reload_quote_sheet_terms()
            self.write_json(get_quote_sheet_terms_public())
            return
        if self.path == "/api/quote-sheet/payment-accounts/reload":
            reload_company_payment_accounts()
            self.write_json(get_company_payment_accounts_public())
            return

        if self.path in ("/api/quote", "/api/quotes/save"):
            if wecom_enabled():
                auth = _require_front_sales_auth(self)
                if auth is None:
                    return
            payload = self.read_json()
            self._cookie_session_id = self.ensure_session_id()
            self._dual_quote_trace = {
                "t0": time.perf_counter(),
                "user_text": str(payload.get("user_prompt") or payload.get("prompt") or "").strip(),
            }
            _log_quote_stage(
                self,
                "request_received",
                route=str(getattr(self, "path", "") or ""),
            )
            att_err = normalize_quote_request_message_and_attachments(payload)
            if att_err:
                self.write_json(
                    {"error": "invalid_attachments", "message": att_err},
                    status=400,
                )
                return
            _log_quote_stage(
                self,
                "parse_payload_done",
                embedding_skip=not embedding_enabled(),
            )
            if self.handle_quote_client_actions(payload):
                return
            sc_raw = payload.get("session_context")
            sc = sc_raw if isinstance(sc_raw, dict) else {}
            active_quote_id = _resolve_active_quote_id_from_context(self._cookie_session_id, sc)
            has_active_quote = bool(active_quote_id)
            structure_confirmed_early = _parse_boolish(
                payload.get("structure_confirmed")
                or payload.get("structure_confirmed_by_user")
                or payload.get("confirm_structure")
            )
            request_route = route_quote_request(
                payload,
                has_upload=self.has_sheet_blob_in_payload(payload),
                has_active_quote=has_active_quote,
            )
            self._request_route = request_route
            payload.update(_route_fields(request_route))
            _log_quote_stage(
                self,
                "route_done",
                route_intent=str(request_route.route_intent or ""),
                structure_confirmed=structure_confirmed_early,
            )
            if request_route.route_intent == ROUTE_CLARIFY and not structure_confirmed_early:
                user_q = str(
                    payload.get("message_text")
                    or payload.get("user_prompt")
                    or payload.get("prompt")
                    or ""
                )
                if _try_business_assistant_response(
                    self,
                    user_q,
                    payload,
                    has_active_quote=has_active_quote,
                    has_upload=self.has_sheet_blob_in_payload(payload),
                ):
                    return
                self.write_json(
                    _clarify_response_for_route(
                        request_route,
                        user_text=user_q,
                        has_active_quote=has_active_quote,
                        has_upload=self.has_sheet_blob_in_payload(payload),
                    )
                )
                return
            if request_route.route_intent == ROUTE_QUOTE_PATCH and not structure_confirmed_early:
                if self.handle_session_intent_quote(payload):
                    return
                user_q = str(
                    payload.get("message_text")
                    or payload.get("user_prompt")
                    or payload.get("prompt")
                    or ""
                )
                if _try_business_assistant_response(
                    self,
                    user_q,
                    payload,
                    has_active_quote=has_active_quote,
                    has_upload=self.has_sheet_blob_in_payload(payload),
                ):
                    return
            if request_route.route_intent in {ROUTE_QA, ROUTE_ADMIN_ACTION} and not structure_confirmed_early:
                user_q = str(
                    payload.get("message_text")
                    or payload.get("user_prompt")
                    or payload.get("prompt")
                    or ""
                )
                qa_resp = _qa_response_for_route(user_q, sid=self._cookie_session_id)
                if request_route.route_intent == ROUTE_ADMIN_ACTION:
                    qa_resp["intent"] = "ADMIN_ACTION"
                self.write_json(qa_resp)
                return
            if request_route.route_intent == ROUTE_CAPABILITY_HELP and not structure_confirmed_early:
                self.write_json(_capability_help_response())
                return
            if request_route.route_intent in {ROUTE_EXPLAIN, ROUTE_COMPARE_EXPLAIN} and not structure_confirmed_early:
                user_q = str(
                    payload.get("message_text")
                    or payload.get("user_prompt")
                    or payload.get("prompt")
                    or ""
                )
                if has_active_quote:
                    sid = self._cookie_session_id or self.ensure_session_id()
                    qid = _resolve_active_quote_id_from_context(
                        sid,
                        payload.get("session_context") if isinstance(payload.get("session_context"), dict) else {},
                    )
                    if qid and GLOBAL_SESSION_STORE.validate_quote_id(sid, qid):
                        last_res = GLOBAL_SESSION_STORE.get_last_quote_result(sid, qid) or {}
                        if isinstance(last_res, dict) and last_res.get("tiers"):
                            sync = (
                                last_res.get("price_kb_sync")
                                if isinstance(last_res.get("price_kb_sync"), dict)
                                else None
                            )
                            st = dict(get_kimi_status()) if isinstance(get_kimi_status(), dict) else {}
                            st.setdefault("agent", "quote_explain_local")
                            self.write_json(
                                build_explain_response_payload(
                                    last_res,
                                    user_question=user_q,
                                    price_kb_sync=sync,
                                    llm_status=st,
                                )
                            )
                            return
                self.write_json(
                    {
                        "quote_ready": False,
                        "assistant_message": (
                            "已收到文件。你这条消息是“解释/对比”意图，我先不自动重跑报价。"
                            "请补一句对比目标（例如：和哪一版业务员结果对比），或发送“开始报价”再进入报价流程。"
                        ),
                        "intent": "QUOTE_EXPLAIN",
                        "llm_status": get_kimi_status(),
                    }
                )
                return
            if self.handle_session_intent_quote(payload):
                return
            sheet_parse_result = None
            has_uploaded_sheet = False
            demand_parse_result: DemandParseResult | None = None
            simple_bom_result: SimpleBomParseResult | None = None
            try:
                demand_parse_result = self.try_parse_demand_template(payload)
                if demand_parse_result is not None:
                    payload, sheet_parse_result = self.attach_demand_items(
                        payload, demand_parse_result
                    )
                    has_uploaded_sheet = True
                else:
                    simple_bom_result = self.try_parse_simple_bom(payload)
                    if simple_bom_result is not None:
                        payload, sheet_parse_result = self.attach_simple_bom_items(
                            payload, simple_bom_result
                        )
                        has_uploaded_sheet = True
                    else:
                        payload, sheet_parse_result = self.attach_uploaded_sheet_items(payload)
                        has_uploaded_sheet = sheet_parse_result is not None
            except SheetParseError as error:
                self.write_json(
                    {"error": "sheet_parse_failed", "message": str(error)},
                    status=400,
                )
                return
            _log_quote_stage(
                self,
                "sheet_parse_done",
                has_upload=has_uploaded_sheet,
                demand=bool(demand_parse_result),
                simple_bom=bool(simple_bom_result),
            )

            enrich_payload_size_variants(payload)
            if isinstance(sheet_parse_result, dict) and payload.get("size_variants"):
                sheet_parse_result["size_variants"] = copy.deepcopy(payload.get("size_variants"))
                sheet_parse_result["multi_size"] = bool(payload.get("multi_size"))

            llm_status = get_kimi_status()
            llm_audit_collector = LlmAuditCollector()
            llm_audit_collector.seed_from_status(
                llm_status if isinstance(llm_status, dict) else {}
            )
            has_structured_demand = demand_parse_result is not None or simple_bom_result is not None
            user_text = str(payload.get("user_prompt") or payload.get("prompt") or "").strip()
            text_dimension_quote_done = False
            demand_locked_pf: float | None = None
            if demand_parse_result is not None and demand_parse_result.quote_settings.get("processing_fee_locked"):
                try:
                    demand_locked_pf = float(demand_parse_result.quote_settings["processing_fee"])
                except (TypeError, ValueError, KeyError):
                    demand_locked_pf = None
            structure_confirmed = _parse_boolish(
                payload.get("structure_confirmed")
                or payload.get("structure_confirmed_by_user")
                or payload.get("confirm_structure")
            )
            if (
                not has_uploaded_sheet
                and not has_structured_demand
                and not (isinstance(payload.get("items"), list) and len(payload.get("items") or []) > 0)
                and not user_prompt_has_quote_intent(user_text)
            ):
                if _try_business_assistant_response(
                    self,
                    user_text,
                    payload,
                    has_active_quote=has_active_quote,
                    has_upload=False,
                ):
                    return
                self.write_json(
                    {
                        "quote_ready": False,
                        "assistant_message": DEFERRED_QUOTE_HINT,
                        "llm_status": llm_status,
                    }
                )
                return

            if (
                not has_uploaded_sheet
                and not has_structured_demand
                and is_new_quote_text_priority(user_text)
            ):
                synth_items, syn_st, p_name, p_size, p_qtys = synthesize_bom_from_new_quote_text(
                    user_text
                )
                llm_audit_collector.record_stage(
                    "text_bom_synthesis",
                    syn_st if isinstance(syn_st, dict) else {},
                    input_rows=0,
                    output_rows=len(synth_items) if synth_items else 0,
                )
                if not synth_items:
                    err_msg = ""
                    if isinstance(syn_st, dict):
                        err_msg = str(syn_st.get("error_message") or "").strip()
                    merged_st = dict(llm_status)
                    if isinstance(syn_st, dict):
                        merged_st.update({k: v for k, v in syn_st.items() if v not in (None, "")})
                    self.write_json(
                        {
                            "quote_ready": False,
                            "assistant_message": err_msg
                            or "无法根据描述生成物料清单，请补充尺寸与材料名称，或直接上传表格。",
                            "intent": "new_quote_text",
                            "llm_status": merged_st,
                            "llm_audit": build_llm_audit(llm_audit_collector, merged_st),
                        }
                    )
                    return
                kb0 = self._get_price_kb_safely()
                payload["items"] = self._enrich_skeleton_items_with_kb(synth_items, kb0)
                payload["items"] = dedupe_composite_overlapping_fabric_rows(list(payload.get("items") or []))
                payload["product_name"] = p_name
                payload["quantities"] = list(p_qtys)
                before_demand_items = copy.deepcopy(list(payload.get("items") or []))
                merged_items, dem_st = complete_demand_quote(
                    product={"name": p_name, "type": "", "size": p_size},
                    items=payload["items"],
                    inline_prices=[],
                    structure_text="",
                    user_prompt=user_text,
                    locked_processing_fee=None,
                )
                payload["items"] = merged_items
                llm_audit_collector.record_stage(
                    "demand_completion",
                    dem_st if isinstance(dem_st, dict) else {},
                    input_rows=len(before_demand_items),
                    output_rows=len(merged_items),
                    before_items=before_demand_items,
                    after_items=merged_items,
                )
                merged_st = dict(llm_status)
                if isinstance(syn_st, dict):
                    merged_st.update({k: v for k, v in syn_st.items() if v not in (None, "")})
                if isinstance(dem_st, dict):
                    merged_st.update({k: v for k, v in dem_st.items() if v not in (None, "")})
                llm_status = merged_st
                text_dimension_quote_done = True
                has_structured_demand = True
                sheet_parse_result = {
                    "file_name": "文字描述询价",
                    "sheet_name": "",
                    "row_count": len(merged_items),
                    "item_count": len(merged_items),
                    "demand_template": False,
                    "from_text_dimensions": True,
                }

            if demand_parse_result is not None:
                raw_items = list(payload.get("items") or [])
                payload["items"] = dedupe_composite_overlapping_fabric_rows(raw_items)
                apply_structure_usage_hints(
                    payload["items"],
                    demand_parse_result.structure_text or "",
                    product_size=demand_parse_result.product_size or {},
                )
                apply_bag_quote_preparse(
                    payload,
                    structure_text=str(demand_parse_result.structure_text or ""),
                    product_type=str(demand_parse_result.product_type or ""),
                    product_name=str(demand_parse_result.product_name or ""),
                    user_prompt=user_text,
                )
                if structure_confirmed:
                    if isinstance(llm_status, dict):
                        llm_status = dict(llm_status)
                        llm_status["structure_confirmation_fast_path"] = True
                        llm_status["demand_completion_skipped"] = "structure_confirmed_local"
                    llm_audit_collector.record_skipped(
                        "demand_completion",
                        "structure_confirmed_local_path",
                    )
                elif isinstance(llm_status, dict):
                    llm_status = dict(llm_status)
                    llm_status["structure_confirmation_fast_path"] = True
                    llm_audit_collector.record_skipped(
                        "demand_completion",
                        "structure_confirmation_required",
                    )
            elif simple_bom_result is not None:
                apply_structure_usage_hints(
                    payload.get("items") or [],
                    simple_bom_result.structure_text or "",
                    product_size=simple_bom_result.product_size or {},
                )
                apply_bag_quote_preparse(
                    payload,
                    structure_text=str(simple_bom_result.structure_text or ""),
                    product_type="",
                    product_name=str(simple_bom_result.product_name or ""),
                    user_prompt=user_text,
                )
                if structure_confirmed:
                    if isinstance(llm_status, dict):
                        llm_status = dict(llm_status)
                        llm_status["structure_confirmation_fast_path"] = True
                        llm_status["demand_completion_skipped"] = "structure_confirmed_local"
                    llm_audit_collector.record_skipped(
                        "demand_completion",
                        "structure_confirmed_local_path",
                    )
                elif isinstance(llm_status, dict):
                    llm_status = dict(llm_status)
                    llm_status["structure_confirmation_fast_path"] = True
                    llm_audit_collector.record_skipped(
                        "demand_completion",
                        "structure_confirmation_required",
                    )
            elif (
                self.should_use_kimi_autofill(payload)
                and not text_dimension_quote_done
                and not _parse_boolish(
                    payload.get("structure_confirmed")
                    or payload.get("structure_confirmed_by_user")
                    or payload.get("confirm_structure")
                )
            ):
                items = payload.get("items", [])
                if isinstance(items, list):
                    user_prompt = str(payload.get("user_prompt") or payload.get("prompt") or "").strip()
                    vision_imgs = payload.get("_composer_vision_images")
                    vision_tuple = tuple(vision_imgs) if isinstance(vision_imgs, tuple) else tuple(vision_imgs or ())
                    before_autofill = copy.deepcopy(items)
                    merged_items, llm_status = autofill_items_with_kimi(
                        items,
                        user_prompt=user_prompt,
                        structure_vision_images=vision_tuple if vision_tuple else None,
                    )
                    payload["items"] = merged_items
                    llm_audit_collector.record_stage(
                        "items_autofill",
                        llm_status if isinstance(llm_status, dict) else {},
                        input_rows=len(before_autofill),
                        output_rows=len(merged_items),
                        before_items=before_autofill,
                        after_items=merged_items,
                    )

            normalized_items = payload.get("items")
            if not isinstance(normalized_items, list):
                normalized_items = []
            normalized_items = apply_material_validity_layer(list(normalized_items))
            for row in normalized_items:
                if isinstance(row, dict) and not bool(row.get("kb_hit")) and not should_skip_knowledge_learn_row(row):
                    enqueue_knowledge_learn_after_rule_miss(
                        str(row.get("name") or ""),
                        str(row.get("spec") or ""),
                    )
            normalized_items = merge_duplicate_width_label_rows(normalized_items)
            normalized_items = collapse_fabric_reverse_use_shadow_rows(normalized_items)
            reconcile_fabric_charge_totals(normalized_items)
            normalized_items = drop_structure_duplicate_markup_rows(normalized_items)
            normalized_items = drop_zero_subtotal_merge_placeholder_rows(normalized_items)
            normalized_items = drop_duplicate_structure_narrative_rows(normalized_items)
            # Final pass: if sheet provided explicit calc methods, prefer them.
            calc_by_name = payload.get("_sheet_calc_note_by_name")
            if isinstance(calc_by_name, dict) and calc_by_name:
                for row in normalized_items:
                    if not isinstance(row, dict):
                        continue
                    key = _normalize_material_key(row.get("name"))
                    if not key:
                        continue
                    explicit = str(calc_by_name.get(key) or "").strip()
                    if not explicit:
                        continue
                    have = str(row.get("calc_note") or "").strip()
                    if _is_specific_calc_note(explicit) and (not have or _is_generic_calc_note(have)):
                        row["calc_note"] = explicit
            payload["items"] = normalized_items
            calc_mode = str(payload.get("calc_note_mode") or "smart").strip().lower()
            payload["enable_calc_note_fallback"] = calc_mode != "strict"
            self._inject_quotation_detail_calc_notes(payload)
            structure_blob = ""
            if demand_parse_result is not None:
                structure_blob = str(demand_parse_result.structure_text or "").strip()
            elif simple_bom_result is not None:
                structure_blob = str(simple_bom_result.structure_text or "").strip()
            if structure_blob:
                rows_st = payload.get("items")
                if isinstance(rows_st, list):
                    payload["items"] = enrich_items_calc_note_from_structure(list(rows_st), structure_blob)
            size_for_tighten: dict | None = None
            if demand_parse_result is not None:
                size_for_tighten = demand_parse_result.product_size
            elif simple_bom_result is not None:
                size_for_tighten = simple_bom_result.product_size
            if size_for_tighten and isinstance(payload.get("items"), list):
                tight_meta = tighten_small_bag_usage_amounts(
                    payload["items"],
                    product_size=size_for_tighten,
                    structure_text=structure_blob,
                )
                if isinstance(llm_status, dict) and tight_meta.get("adjusted"):
                    llm_status["structure_cost_recheck"] = tight_meta
            payload["structure_text_snapshot"] = structure_blob
            if demand_parse_result is not None:
                payload["product_type"] = str(demand_parse_result.product_type or "").strip()
            elif simple_bom_result is not None:
                payload["product_type"] = str(simple_bom_result.product_name or "").strip()

            if structure_blob:
                apply_bag_quote_preparse(
                    payload,
                    structure_text=structure_blob,
                    product_type=str(payload.get("product_type") or "").strip(),
                    product_name=str(payload.get("product_name") or "").strip(),
                    user_prompt=user_text,
                )
                payload["bag_structure_candidates_merged"] = True
                if isinstance(payload.get("items"), list):
                    payload["items"] = apply_material_validity_layer(list(payload["items"]))

            try:
                items_for_log = payload.get("items") if isinstance(payload.get("items"), list) else []
                calc_hits = 0
                for r in items_for_log:
                    if not isinstance(r, dict):
                        continue
                    if str(r.get("calc_note") or "").strip():
                        calc_hits += 1
                print(
                    f"[calc-note] hits={calc_hits}/{len(items_for_log)} "
                    f"mode={calc_mode} fallback={bool(payload.get('enable_calc_note_fallback', False))}"
                )
            except Exception:
                pass

            self._apply_llm_suggested_processing_fee(
                payload, llm_status, demand_parse_result
            )

            payload, enrichment_report = enrich_missing_quote_data(payload)
            enrich_payload_material_spec_usage(payload)
            if structure_confirmed and isinstance(payload.get("items"), list):
                sc_patch = payload.get("structure_confirmation_items")
                if sc_patch is None:
                    sc_patch = payload.get("structure_items_patch")
                payload["items"] = merge_structure_confirmation_user_items(
                    list(payload["items"]),
                    sc_patch if isinstance(sc_patch, list) else [],
                )
                _log_quote_stage(
                    self,
                    "structure_confirm_merge_done",
                    llm=False,
                    embedding_skip=not embedding_enabled(),
                    **_quote_items_stage_metrics(payload.get("items")),
                )
                allow_estimate = _parse_boolish(
                    payload.get("allow_estimate_with_incomplete_items")
                    or payload.get("allow_incomplete_structure_quote")
                )
                ok_items, gap_summary = validate_structure_items_for_formal_quote(
                    list(payload.get("items") or []),
                    allow_estimate=allow_estimate,
                )
                if not ok_items:
                    _log_quote_stage(
                        self,
                        "material_confirm_blocked",
                        llm=False,
                        embedding_skip=not embedding_enabled(),
                        **{
                            k: gap_summary[k]
                            for k in ("gap_count", "pending_count", "missing_price_count")
                            if k in gap_summary
                        },
                    )
                    self.write_json(
                        {
                            "error": "incomplete_structure_items",
                            "message": str(gap_summary.get("message") or ""),
                            "quote_ready": False,
                            "assistant_message": str(gap_summary.get("message") or ""),
                            "structure_quote_gaps": gap_summary.get("gaps") or [],
                            "llm_status": llm_status,
                        },
                        status=400,
                    )
                    return
                payload["items"] = confirm_material_candidates_for_quote(
                    apply_material_validity_layer(list(payload["items"]))
                )
                _log_quote_stage(
                    self,
                    "material_confirm_done",
                    llm=False,
                    embedding_skip=not embedding_enabled(),
                    **_quote_items_stage_metrics(payload.get("items")),
                )
                if allow_estimate or int(gap_summary.get("gap_count") or 0) > 0:
                    payload["items"] = prepare_structure_rows_for_market_estimate(
                        list(payload["items"])
                    )
                _log_quote_stage(
                    self,
                    "market_estimate_done",
                    llm=False,
                    allow_estimate=allow_estimate,
                    embedding_skip=not embedding_enabled(),
                    **_quote_items_stage_metrics(payload.get("items")),
                )
            if has_uploaded_sheet and not structure_confirmed:
                resp = build_structure_confirmation_payload(
                    payload,
                    sheet_parse_result=sheet_parse_result,
                    structure_text=str(payload.get("structure_text_snapshot") or ""),
                    enrichment_report=enrichment_report,
                )
                resp["llm_status"] = llm_status
                resp["llm_audit"] = build_llm_audit(llm_audit_collector, llm_status)
                if sheet_parse_result is not None:
                    resp["sheet_parse"] = sheet_parse_result
                self.write_json(resp)
                return

            if (
                not has_uploaded_sheet
                and not has_structured_demand
                and len(normalized_items) == 0
            ):
                self.write_json(
                    {
                        "quote_ready": False,
                        "assistant_message": QUOTE_NEEDS_UPLOAD_OR_ITEMS_HINT,
                        "llm_status": llm_status,
                    }
                )
                return

            if has_uploaded_sheet and not has_effective_material_pricing(payload.get("items")):
                billing = ""
                if isinstance(llm_status, dict):
                    billing = str(llm_status.get("billing_reminder") or "").strip()
                llm_error = str(llm_status.get("error") or "").strip() if isinstance(llm_status, dict) else ""
                base_tail = "未识别到有效物料价格，请检查表格列映射或补充单价列后重试。"
                if billing and llm_error:
                    error_message = (
                        f"{billing}\n"
                        f"模型补全未成功（{llm_error}）。请先到 Moonshot/Kimi 控制台核对余额/套餐，并检查表格与 API 配置。\n"
                        f"{base_tail}"
                    )
                elif billing:
                    error_message = f"{billing}\n{base_tail}"
                elif llm_error:
                    error_message = (
                        f"{base_tail}（模型调用：{llm_error}）。"
                        "请检查 AI 模型 API Key / Base URL / 模型名配置。"
                    )
                else:
                    error_message = base_tail
                self.write_json(
                    {
                        "error": "invalid_material_pricing",
                        "message": error_message,
                        "llm_status": llm_status,
                        "sheet_parse": sheet_parse_result or {},
                    },
                    status=400,
                )
                return
            apply_user_prompt_quote_overrides(payload)
            payload.pop("_composer_vision_images", None)
            pre_clarify = None if structure_confirmed else _maybe_pre_quote_clarify(payload)
            if pre_clarify is not None:
                pre_clarify["llm_status"] = llm_status
                self.write_json(pre_clarify)
                return
            if payload.get("multi_size"):
                payload["_size_variant_items_template"] = copy.deepcopy(payload.get("items") or [])
            _log_quote_stage(
                self,
                "pre_calculate",
                structure_confirmed=structure_confirmed,
                llm=False,
                embedding_skip=not embedding_enabled(),
                **_quote_items_stage_metrics(payload.get("items")),
            )
            try:
                response = _calculate_quote_with_guard(self, payload)
            except QuoteCalculateTimeoutError as exc:
                self.write_json(
                    {
                        "error": "quote_timeout",
                        "message": str(exc) or QUOTE_TIMEOUT_USER_MESSAGE,
                        "quote_ready": False,
                        "assistant_message": str(exc) or QUOTE_TIMEOUT_USER_MESSAGE,
                        "llm_status": llm_status,
                    },
                    status=504,
                )
                return
            merge_quote_sales_from_payload(response, payload)
            self._apply_quote_output_gate(response, payload)
            response["quote_ready"] = True
            response["quote_id"] = str(uuid.uuid4())
            response["llm_status"] = llm_status
            response["llm_audit"] = build_llm_audit(llm_audit_collector, llm_status)
            response["missing_data_enrichment"] = enrichment_report
            if text_dimension_quote_done:
                response["intent"] = "new_quote_text"
            if isinstance(llm_status, dict):
                summary = str(llm_status.pop("consultant_summary", "") or "").strip()
                if summary:
                    response["consultant_summary"] = summary
            if sheet_parse_result is not None:
                response["sheet_parse"] = sheet_parse_result
            sheet_fn = ""
            if isinstance(sheet_parse_result, dict):
                sheet_fn = str(sheet_parse_result.get("file_name") or "").strip()
            if not sheet_fn and isinstance(payload.get("uploaded_sheet"), dict):
                sheet_fn = str(payload["uploaded_sheet"].get("name") or "").strip()
            snap = copy.deepcopy(payload)
            if isinstance(snap, dict):
                snap.pop("uploaded_sheet", None)
                _sync_structure_checklist_into_payload(snap, response)
            series_uid = resolve_quote_series_uid(self._cookie_session_id, payload, response)
            if not _persist_quote_with_sales_user(
                self,
                series_uid=series_uid,
                response=response,
                payload=payload,
                sheet_fn=sheet_fn,
                uploaded_sheet=payload.get("uploaded_sheet") if isinstance(payload.get("uploaded_sheet"), dict) else None,
                user_message=user_text,
            ):
                return
            _log_quote_stage(
                self,
                "persist_done",
                quote_id=str(response.get("quote_id") or ""),
                embedding_skip=not embedding_enabled(),
            )
            _safe_sync_price_kb_from_quote(response)
            GLOBAL_SESSION_STORE.set_current_quote(
                self._cookie_session_id,
                response["quote_id"],
                sheet_fn,
                snap,
                response,
                quote_series_uid=series_uid,
            )
            _sync_agent_graph_quote_context(
                sid=self._cookie_session_id,
                payload_snapshot=snap,
                quote_result=response,
                user_message=user_text,
                local_intent=str(response.get("intent") or "NEW_QUOTE"),
            )
            self.write_json(response)
            return
        if self.path == "/api/quote/advise":
            payload = self.read_json()
            if not isinstance(payload, dict):
                self.write_json({"error": "invalid_request", "message": "请求体须为 JSON 对象。"}, status=400)
                return
            user_message = str(payload.get("user_message") or "").strip()
            interaction = str(payload.get("interaction") or "explain").strip().lower()
            quote_snapshot = payload.get("quote_snapshot")
            file_hint = str(payload.get("file_hint") or "").strip()
            llm_status = get_kimi_status()

            if not user_message:
                self.write_json({"error": "invalid_request", "message": "缺少 user_message。"}, status=400)
                return

            if not isinstance(quote_snapshot, dict) or not quote_snapshot.get("tiers"):
                self.write_json(
                    {
                        "reply_type": "text",
                        "text": "当前没有可解析的报价快照。请先完成一次报价或 @ 指定历史报价文件。",
                        "llm_status": llm_status,
                    }
                )
                return

            want_process = _interaction_wants_process_only(user_message, interaction)
            if want_process:
                process = build_process_explainer_payload(quote_snapshot)
                self.write_json(
                    {
                        "reply_type": "process_card",
                        "title": "计算过程拆解",
                        "file_hint": file_hint,
                        "process": process,
                        "llm_status": llm_status,
                    }
                )
                return

            sid = self.ensure_session_id()
            answer, agent_state = _invoke_agent_quote_explain(
                sid=sid,
                user_message=user_message,
                payload_snapshot={},
                quote_result=quote_snapshot,
            )
            merged = dict(llm_status)
            if isinstance(agent_state, dict):
                merged["agent"] = "langgraph"
                merged["agent_intent"] = agent_state.get("last_intent")
            self.write_json({"reply_type": "text", "text": answer, "llm_status": merged})
            return
        if self.path == "/api/feedback":
            payload = self.read_json()
            self.store_feedback(payload)
            self.write_json({"ok": True, "message": "feedback saved"})
            return
        self._discard_request_body()
        self.write_json({"error": "not found"}, status=404)

    def do_DELETE(self) -> None:
        self._request_started_at = time.time()
        self._request_id = self.headers.get("X-Request-ID") or _short_request_id()
        site = getattr(self.server, "_quote_site", "front")
        if site != "admin":
            self.write_json({"error": "not found"}, status=404)
            return
        if not self._admin_client_ip_allowed():
            self.write_json(
                {"error": "forbidden", "message": "后台访问来源不在允许列表（QUOTE_ADMIN_ALLOW_IPS）。"},
                status=403,
            )
            return
        parsed_req = urlparse(self.path)
        req_path = _canonical_http_path_only(self.path)
        m_corr_del = re.match(r"^/admin-api/quotes/([^/]+)/correction-sheet/?$", req_path)
        if m_corr_del:
            if not self.require_admin_json_api():
                return
            quote_uid = unquote(m_corr_del.group(1))
            try:
                result = delete_admin_correction_sheet(quote_uid, deleted_by="admin")
            except ValueError as exc:
                msg = str(exc)
                if msg == "not_found":
                    self.write_json(
                        {"error": "not_found", "message": _ADMIN_QUOTE_NOT_FOUND_MSG},
                        status=404,
                    )
                    return
                if msg == "no_correction_sheet":
                    self.write_json(
                        {
                            "error": "no_correction_sheet",
                            "message": "当前没有管理员修正版表格。",
                        },
                        status=404,
                    )
                    return
                self.write_json({"error": "invalid_request", "message": msg}, status=400)
                return
            self.write_json(result)
            return
        m_calc_del = re.match(r"^/admin-api/quotes/([^/]+)/calculated-sheet/?$", req_path)
        if m_calc_del:
            if not self.require_admin_json_api():
                return
            quote_uid = unquote(m_calc_del.group(1))
            try:
                result = delete_admin_calculated_sheet(quote_uid, deleted_by="admin")
            except ValueError as exc:
                msg = str(exc)
                if msg == "not_found":
                    self.write_json(
                        {"error": "not_found", "message": _ADMIN_QUOTE_NOT_FOUND_MSG},
                        status=404,
                    )
                    return
                if msg == "no_calculated_sheet":
                    self.write_json(
                        {
                            "error": "no_calculated_sheet",
                            "message": "当前没有管理员自算表格。",
                        },
                        status=404,
                    )
                    return
                self.write_json({"error": "invalid_request", "message": msg}, status=400)
                return
            self.write_json(result)
            return
        m_price_del = re.match(r"^/admin-api/prices/(row-\d+)$", req_path, re.I)
        if m_price_del:
            if not admin_http_access_ok(self.headers):
                self.write_json({"error": "forbidden", "message": "需要管理员权限。"}, status=403)
                return
            qs = parse_qs(parsed_req.query)
            updated_by = (qs.get("updated_by", ["admin"])[0] or "admin").strip() or "admin"
            qs_name = (qs.get("name", [""])[0] or "").strip()
            qs_spec = (qs.get("spec", [""])[0] or "").strip()
            qs_price = (qs.get("price", [""])[0] or "").strip()
            _handle_admin_price_delete(
                unquote(m_price_del.group(1)),
                updated_by=updated_by,
                write_json=self.write_json,
                name=qs_name,
                spec=qs_spec,
                price=qs_price,
            )
            return

        m_del = re.match(r"^/admin-api/quotes/([^/]+)$", req_path)
        if not m_del:
            self.write_json({"error": "not found"}, status=404)
            return
        if not self.require_admin_json_api():
            return
        qida = unquote(m_del.group(1))
        if delete_quote_series(qida):
            self.write_json({"ok": True})
        else:
            self.write_json({"error": "not_found", "message": "记录不存在。"}, status=404)

    def should_use_kimi_autofill(self, payload: dict) -> bool:
        # During sheet parsing hardening, disable AI autofill when an upload is provided.
        # This keeps the raw parsed rows stable and easier to validate.
        uploaded_sheet = payload.get("uploaded_sheet") if isinstance(payload, dict) else None
        if isinstance(uploaded_sheet, dict):
            return False
        if "enable_kimi_autofill" not in payload:
            return True
        value = payload.get("enable_kimi_autofill")
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y"}

    def _inject_quotation_detail_calc_notes(self, payload: dict) -> None:
        """从整本 xlsx 报价明细表补 calc_note（不覆盖已有）；解决走通用 BOM 解析时丢掉「计算方式」。"""
        if not isinstance(payload, dict):
            return
        rows = payload.get("items")
        if not isinstance(rows, list) or not rows:
            return
        us = payload.get("uploaded_sheet")
        if not isinstance(us, dict):
            return
        fn = str(us.get("name") or "").lower()
        raw_b64 = str(us.get("content_base64") or "").strip()
        if not raw_b64 or not fn.endswith(".xlsx"):
            return
        import base64

        try:
            file_bytes = base64.b64decode(raw_b64, validate=True)
        except Exception:
            return
        try:
            mats = quotation_detail_materials_bundle_from_entire_xlsx(file_bytes)
        except Exception:
            return
        if not mats:
            return
        merged = enrich_quote_item_rows_with_quotation_calc(list(rows), mats)
        # Prefer explicit sheet calc notes over generic fallback phrases.
        existing_by_name: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            k = _normalize_material_key(row.get("name"))
            if not k:
                continue
            calc = str(row.get("calc_note") or row.get("calc_method") or "").strip()
            if calc:
                existing_by_name[k] = calc
        for row in merged:
            if not isinstance(row, dict):
                continue
            k = _normalize_material_key(row.get("name"))
            if not k:
                continue
            have = str(row.get("calc_note") or "").strip()
            force = existing_by_name.get(k, "")
            if force and _is_specific_calc_note(force) and (not have or _is_generic_calc_note(have)):
                row["calc_note"] = force
        payload["items"] = merged

    def try_parse_demand_template(self, payload: dict) -> DemandParseResult | None:
        """Detect whether the upload is a "需求表(填写区)" template and, if so,
        parse it. Returns None for non-templates so the legacy BOM parser
        can run."""
        if not isinstance(payload, dict):
            return None
        uploaded_sheet = payload.get("uploaded_sheet")
        if not isinstance(uploaded_sheet, dict):
            return None
        try:
            parsed = parse_demand_from_payload(uploaded_sheet)
        except SheetParseError:
            return None
        if not parsed.sections or not parsed.materials:
            return None
        # Final guard: require multiple section markers to avoid false
        # positives on plain BOM sheets that happen to have one A/B header.
        if len(parsed.sections) < 3:
            return None
        return parsed

    def attach_demand_items(
        self,
        payload: dict,
        demand: DemandParseResult,
    ) -> tuple[dict, dict]:
        """Convert demand-form materials into BOM rows: query the price KB
        for each material, attach KB price when hit, leave usage/missing
        prices blank for the LLM step downstream."""
        kb = self._get_price_kb_safely()
        items: list[dict[str, object]] = []
        kb_hits: list[dict[str, object]] = []
        kb_misses: list[str] = []

        for material in demand.materials:
            row: dict[str, object] = {
                "name": material.name,
                "role": material.role,
                "spec": material.spec or "-",
                "usage": "-",
                "unit_price": material.inline_price or "-",
                "amount": 0.0,
                "kb_hit": False,
                "kb_score": 0.0,
                "spec_ai": False,
                "usage_ai": False,
                "unit_price_ai": bool(material.inline_price),
                "amount_ai": False,
                "source": "kb" if material.inline_price else "ai",
                "demand_source": material.source,
            }
            qu = str(getattr(material, "quoted_usage", "") or "").strip()
            if qu:
                row["usage"] = qu
                row["_sheet_usage_lock"] = True
                row["usage_ai"] = False
            else:
                uh = usage_hint_from_bracket(str(material.note or ""), str(material.inline_price or ""))
                if uh:
                    row["usage"] = uh
                    row["_structure_usage_lock"] = True
                    row["usage_ai"] = False
            cm = str(getattr(material, "calc_method", "") or "").strip()
            if cm:
                row["calc_note"] = cm
            hit: KBHit | None = None
            if kb is not None:
                hit = kb.lookup(material.name, material.spec)
            if hit is not None:
                entry = hit.entry
                row["unit_price"] = format_kb_entry_price_display(
                    entry,
                    role=material.role,
                    usage=str(row.get("usage") or ""),
                )
                row["unit_price_ai"] = False
                row["kb_hit"] = True
                row["kb_score"] = round(hit.score, 2)
                row["kb_matched_name"] = entry.raw_name
                row["kb_matched_spec"] = entry.raw_spec
                row["kb_auto_learned"] = bool(getattr(entry, "auto_learned", False))
                row["source"] = "kb"
                if entry.raw_spec and (not material.spec or material.spec == "-"):
                    row["spec"] = entry.raw_spec
                kb_hits.append({"name": material.name, "matched": entry.raw_name, "score": row["kb_score"]})
            else:
                kb_misses.append(material.name)
            items.append(row)

        margin = demand.quote_settings.get("gross_margin_rate")
        if margin is not None:
            payload["gross_margin_rate"] = margin
        mold_fee = compute_mold_fee_from_sections(demand.sections)
        payload["mold_fee"] = float(mold_fee)
        mlr = demand.quote_settings.get("management_loss_rate")
        if mlr is not None:
            try:
                payload["management_loss_rate"] = float(mlr)
            except (TypeError, ValueError):
                pass
        sof = demand.quote_settings.get("system_overhead_fixed")
        if sof is not None:
            try:
                payload["system_overhead_fixed"] = float(sof)
            except (TypeError, ValueError):
                pass
        proc_fee = demand.quote_settings.get("processing_fee")
        if proc_fee is not None:
            try:
                payload["processing_fee"] = float(proc_fee)
            except (TypeError, ValueError):
                pass
        if demand.quantities:
            payload["quantities"] = list(demand.quantities)
        payload["items"] = items
        pname = (
            (demand.product_name or "").strip()
            or (demand.product_type or "").strip()
        )
        payload["product_name"] = pname or str(payload.get("product_name") or "").strip()
        if demand.gross_margin_by_quantity:
            payload["gross_margin_by_quantity"] = {
                str(k): float(v) for k, v in demand.gross_margin_by_quantity.items()
            }
        payload["reference_prices"] = list(demand.reference_prices)
        payload["include_fob"] = bool(demand.quote_settings.get("include_fob", True))
        fx_usd = demand.quote_settings.get("fx_usd_rmb")
        if fx_usd is not None and str(fx_usd).strip() != "":
            try:
                payload["usd_cny_rate"] = float(fx_usd)
            except (TypeError, ValueError):
                pass
        payload["quote_params"] = {
            "A": demand.sections.get("A", {}),
            "B": demand.sections.get("B", {}),
            "C": demand.sections.get("C", {}),
            "D": demand.sections.get("D", {}),
            "E": demand.sections.get("E", {}),
            "F": demand.sections.get("F", {}),
            "G": demand.sections.get("G", {}),
        }
        apply_sales_fields_to_payload(payload)
        payload["product_size"] = demand.product_size or {}
        sec_b = demand.sections.get("B", {}) if isinstance(demand.sections.get("B"), dict) else {}
        for size_key in ("成品尺寸", "尺寸", "产品尺寸"):
            raw_size = str(sec_b.get(size_key) or "").strip()
            if raw_size:
                payload["product_size_text"] = raw_size
                break
        if isinstance(sec_b, dict) and sec_b:
            payload["sheet_metadata"] = {str(k): str(v) for k, v in sec_b.items() if str(v or "").strip()}

        sheet_parse_result = {
            "file_name": demand.file_name,
            "sheet_name": demand.sheet_name,
            "row_count": demand.raw_row_count,
            "item_count": len(items),
            "kb_hit_count": len(kb_hits),
            "kb_miss_count": len(kb_misses),
            "kb_hits": kb_hits,
            "kb_misses": kb_misses,
            "demand_template": True,
            "product_name": demand.product_name,
            "product_type": demand.product_type,
            "product_size": demand.product_size,
            "quantities": list(demand.quantities),
            "inline_prices": demand.inline_prices,
            "reference_prices": demand.reference_prices,
            "auxiliary_bom_sheet_names": list(demand.auxiliary_bom_sheet_names),
            "processing_fee_locked": bool(demand.quote_settings.get("processing_fee_locked")),
            "processing_fee_rule": str(demand.quote_settings.get("processing_fee_rule") or ""),
            "include_fob": bool(demand.quote_settings.get("include_fob", True)),
        }
        print(
            f"[demand-parse] file={demand.file_name} sheet={demand.sheet_name} "
            f"materials={len(demand.materials)} kb_hit={len(kb_hits)} miss={len(kb_misses)}"
        )
        return payload, sheet_parse_result

    def _get_price_kb_safely(self):
        try:
            return get_price_kb()
        except (FileNotFoundError, SheetParseError) as exc:
            print(f"[price-kb] load failed: {exc}")
            return None

    def _enrich_skeleton_items_with_kb(self, items: list[dict], kb) -> list[dict[str, object]]:
        """文字生成的 BOM 骨架：尽量用知识库标价覆盖单价。"""
        rows: list[dict[str, object]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            spec = str(raw.get("spec") or "-").strip() or "-"
            row: dict[str, object] = {
                "name": name,
                "role": str(raw.get("role") or "辅料").strip() or "辅料",
                "spec": spec,
                "usage": "-",
                "unit_price": "-",
                "amount": 0.0,
                "kb_hit": False,
                "kb_score": 0.0,
                "spec_ai": bool(raw.get("spec_ai", True)),
                "usage_ai": False,
                "unit_price_ai": True,
                "amount_ai": False,
                "source": "ai",
            }
            hit: KBHit | None = None
            if kb is not None:
                hit = kb.lookup(name, spec)
            if hit is not None:
                entry = hit.entry
                row["unit_price"] = format_kb_entry_price_display(
                    entry,
                    role=str(row.get("role") or ""),
                    usage=str(row.get("usage") or ""),
                )
                row["unit_price_ai"] = False
                row["kb_hit"] = True
                row["kb_score"] = round(hit.score, 2)
                row["kb_matched_name"] = entry.raw_name
                row["kb_matched_spec"] = entry.raw_spec
                row["kb_auto_learned"] = bool(getattr(entry, "auto_learned", False))
                row["source"] = "kb"
                if entry.raw_spec and (not spec or spec == "-"):
                    row["spec"] = entry.raw_spec
            rows.append(row)
        return rows

    def try_parse_simple_bom(self, payload: dict) -> SimpleBomParseResult | None:
        if not isinstance(payload, dict):
            return None
        if isinstance(payload.get("items"), list) and payload.get("items"):
            return None
        uploaded_sheet = payload.get("uploaded_sheet")
        if not isinstance(uploaded_sheet, dict):
            return None
        try:
            parsed = parse_simple_bom_from_payload(uploaded_sheet)
        except SheetParseError:
            return None
        if not parsed.materials:
            return None
        return parsed

    def attach_simple_bom_items(
        self,
        payload: dict,
        parsed: SimpleBomParseResult,
    ) -> tuple[dict, dict]:
        """Convert simple-BOM rows into items for the quote engine.

        Each row already carries its unit_price from the spreadsheet so we
        skip the KB lookup, mark unit_price_ai=False, and let the LLM only
        fill in 用量.
        """
        items: list[dict[str, object]] = []
        for material in parsed.materials:
            has_price = bool(material.unit_price.strip())
            row: dict[str, object] = {
                "name": material.name,
                "role": material.role,
                "spec": material.spec or "-",
                "usage": "-",
                "unit_price": material.unit_price or "-",
                "amount": 0.0,
                "kb_hit": has_price,  # Treat user-entered price as authoritative.
                "kb_score": 1.0 if has_price else 0.0,
                "spec_ai": False,
                "usage_ai": False,
                "unit_price_ai": not has_price,
                "amount_ai": False,
                "source": "kb" if has_price else "ai",
            }
            items.append(row)

        margin = parsed.quote_settings.get("gross_margin_rate")
        if margin is not None:
            payload["gross_margin_rate"] = margin
        if parsed.quote_settings.get("processing_fee") is not None:
            payload["processing_fee"] = parsed.quote_settings["processing_fee"]
        if parsed.quantities:
            payload["quantities"] = list(parsed.quantities)
        payload["items"] = items
        if parsed.product_name:
            payload["product_name"] = parsed.product_name
        payload["reference_prices"] = list(parsed.reference_prices)
        payload["product_size"] = parsed.product_size or {}
        payload["sheet_metadata"] = dict(parsed.metadata)
        size_meta = str(parsed.metadata.get("尺寸") or parsed.metadata.get("成品尺寸") or "").strip()
        if size_meta:
            payload["product_size_text"] = size_meta

        sheet_parse_result = {
            "file_name": parsed.file_name,
            "sheet_name": parsed.sheet_name,
            "row_count": parsed.raw_row_count,
            "item_count": len(items),
            "demand_template": False,
            "simple_bom_template": True,
            "product_name": parsed.product_name,
            "product_size": parsed.product_size,
            "quantities": list(parsed.quantities),
            "metadata": parsed.metadata,
            "reference_prices": parsed.reference_prices,
        }
        print(
            f"[simple-bom-parse] file={parsed.file_name} sheet={parsed.sheet_name} "
            f"materials={len(parsed.materials)} qty={parsed.quantities}"
        )
        return payload, sheet_parse_result

    def attach_uploaded_sheet_items(self, payload: dict) -> tuple[dict, dict | None]:
        if not isinstance(payload, dict):
            return {}, None

        # If the frontend has already confirmed cleaned items, trust these rows directly.
        raw_items = payload.get("items")
        if isinstance(raw_items, list) and raw_items:
            return payload, None

        uploaded_sheet = payload.get("uploaded_sheet")
        if not isinstance(uploaded_sheet, dict):
            return payload, None

        parsed = parse_sheet_items_from_payload(uploaded_sheet)
        self.log_sheet_parse(parsed)
        payload["items"] = parsed["items"]
        payload.setdefault("calc_note_mode", "smart")
        # Keep explicit calc method text for each material so later enrich/LLM
        # steps can restore it if generic fallback text appears.
        calc_note_by_name: dict[str, str] = {}
        for row in payload["items"]:
            if not isinstance(row, dict):
                continue
            k = _normalize_material_key(row.get("name"))
            if not k:
                continue
            calc = str(row.get("calc_note") or "").strip()
            if calc:
                calc_note_by_name[k] = calc
        if calc_note_by_name:
            payload["_sheet_calc_note_by_name"] = calc_note_by_name
        media_summary = enrich_items_with_sheet_media_hints(
            uploaded_sheet,
            str(parsed.get("sheet_name") or ""),
            payload["items"],
        )
        payload["quote_params"] = parsed.get("quote_params", {})
        apply_sales_fields_to_payload(payload)
        sheet_product_name = str(parsed.get("sheet_product_name") or "").strip()
        if sheet_product_name:
            payload["product_name"] = sheet_product_name
        return payload, {
            "file_name": parsed["file_name"],
            "sheet_name": parsed.get("sheet_name", ""),
            "row_count": parsed["row_count"],
            "sheet_row_counts": parsed.get("sheet_row_counts", {}),
            "non_empty_row_count": parsed.get("non_empty_row_count", 0),
            "data_row_count": parsed.get("data_row_count", 0),
            "item_count": parsed["item_count"],
            "filtered_count": parsed.get("filtered_count", 0),
            "scan_summary": parsed.get("scan_summary", {}),
            "media_summary": media_summary,
            "sheet_product_name": parsed.get("sheet_product_name", ""),
            "quote_params": parsed.get("quote_params", {}),
        }

    def log_sheet_parse(self, parsed: dict) -> None:
        file_name = str(parsed.get("file_name", "")).strip() or "-"
        sheet_name = str(parsed.get("sheet_name", "")).strip() or "-"
        item_count = int(parsed.get("item_count", 0) or 0)
        row_count = int(parsed.get("row_count", 0) or 0)
        non_empty_row_count = int(parsed.get("non_empty_row_count", 0) or 0)
        filtered_count = int(parsed.get("filtered_count", 0) or 0)
        scan_summary = parsed.get("scan_summary", {}) if isinstance(parsed.get("scan_summary"), dict) else {}
        sheet_row_counts = (
            parsed.get("sheet_row_counts", {})
            if isinstance(parsed.get("sheet_row_counts"), dict)
            else {}
        )
        print(
            f"[sheet-parse] file={file_name} sheet={sheet_name} "
            f"rows={row_count}/{non_empty_row_count} items={item_count} filtered={filtered_count} "
            f"sheets={sheet_row_counts} scan={scan_summary}"
        )

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def write_json(self, data: dict, status: int = 200) -> None:
        self.write_json_response(data, status=status, extra_headers=None)

    def write_json_response(
        self,
        data: dict,
        *,
        status: int = 200,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        rid = getattr(self, "_request_id", "") or _short_request_id()
        self._request_id = rid
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("request_id", rid)
            route = getattr(self, "_request_route", None)
            if isinstance(route, RequestRoute):
                for key, value in _route_fields(route).items():
                    data.setdefault(key, value)
            if status >= 400:
                err = str(data.get("error_code") or data.get("error") or "request_failed")
                data.setdefault("ok", False)
                data.setdefault("error_code", err)
                data.setdefault("message", str(data.get("message") or data.get("error") or err))
            trace = getattr(self, "_dual_quote_trace", None)
            if trace is not None and isinstance(data, dict):
                path_only = _canonical_http_path_only(getattr(self, "path", "") or "")
                if path_only in {"/api/quote", "/api/quotes/save"}:
                    try:
                        apply_dual_mode_envelope(data, trace=trace, http_status=status)
                    except Exception:
                        pass
                    setattr(self, "_dual_quote_trace", None)
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", rid)
        cookie_val = getattr(self, "_set_session_cookie_id", None)
        if cookie_val:
            self.send_header("Set-Cookie", set_cookie_header_value(cookie_val))
        sales_token = getattr(self, "_set_sales_session_token", None)
        if sales_token:
            hk, hv = set_sales_session_cookie_header(sales_token)
            self.send_header(hk, hv)
        sales_cookie_val = getattr(self, "_set_sales_user_cookie_id", None)
        if sales_cookie_val and not wecom_enabled():
            self.send_header("Set-Cookie", set_sales_user_cookie_header_value(sales_cookie_val))
        sales_name_cookie_val = getattr(self, "_set_sales_user_name_cookie", None)
        if sales_name_cookie_val and not wecom_enabled():
            self.send_header("Set-Cookie", set_sales_user_name_cookie_header_value(sales_name_cookie_val))
        if extra_headers:
            for hk, hv in extra_headers:
                self.send_header(hk, hv)
        self.end_headers()
        self.wfile.write(body)
        started = float(getattr(self, "_request_started_at", time.time()) or time.time())
        _json_log(
            "http_request",
            request_id=rid,
            method=getattr(self, "command", ""),
            path=getattr(self, "path", ""),
            status=status,
            duration_ms=round((time.time() - started) * 1000, 2),
            session_id=getattr(self, "_cookie_session_id", ""),
        )

    def write_file_attachment(self, path: Path, download_name: str, mime_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        disp = url_quote(download_name, safe="")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{disp}")
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, path: Path) -> None:
        resolved = path.resolve()
        if STATIC_DIR.resolve() not in resolved.parents and resolved != (STATIC_DIR / "index.html").resolve():
            self.write_json({"error": "invalid path"}, status=403)
            return
        if not resolved.exists() or not resolved.is_file():
            self.write_json({"error": "not found"}, status=404)
            return

        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if (
            content_type.startswith("text/")
            or content_type in {"application/javascript", "application/x-javascript"}
        ) and "charset=" not in content_type.lower():
            content_type = f"{content_type}; charset=utf-8"
        body = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def store_feedback(self, payload: dict) -> None:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        exists = FEEDBACK_FILE.exists()
        fieldnames = [
            "created_at",
            "product_name",
            "quantity",
            "ai_cost",
            "manual_cost",
            "manual_reason",
        ]
        with FEEDBACK_FILE.open("a", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if not exists:
                writer.writeheader()
            writer.writerow(
                {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "product_name": str(payload.get("product_name", "")).strip(),
                    "quantity": str(payload.get("quantity", "")).strip(),
                    "ai_cost": str(payload.get("ai_cost", "")).strip(),
                    "manual_cost": str(payload.get("manual_cost", "")).strip(),
                    "manual_reason": str(payload.get("manual_reason", "")).strip(),
                }
            )

    def log_message(self, format: str, *args) -> None:
        return


def _warm_embedding_daemon() -> None:
    """首次 BGE 建索引较慢，放后台线程，避免阻塞 ``serve_forever``。"""
    try:
        from core.smart_lookup import warm_embedding_index

        warm_embedding_index()
    except Exception as exc:
        print(f"[embedding] warm skipped: {exc}", flush=True)


def _pending_auto_learn_daemon() -> None:
    """Periodically inject approved pending auto-learn rows when explicitly enabled."""
    if str(os.environ.get("KNOWLEDGE_PENDING_AUTO_APPLY") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    try:
        interval = float(os.environ.get("KNOWLEDGE_PENDING_AUTO_APPLY_INTERVAL_SECONDS", "60"))
    except ValueError:
        interval = 60.0
    interval = max(5.0, interval)

    from core.knowledge_pending_apply import apply_pending_auto_learn

    while True:
        try:
            result = apply_pending_auto_learn()
            if result.total:
                print(
                    "[knowledge-auto-apply] "
                    f"total={result.total} applied={result.applied} "
                    f"existing={result.skipped_existing} invalid={result.invalid} "
                    f"failed={result.failed} kept={result.kept}",
                    flush=True,
                )
                for err in result.errors:
                    print(f"[knowledge-auto-apply] warning: {err}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[knowledge-auto-apply] failed: {exc}", flush=True)
        time.sleep(interval)


def run(host: str = "127.0.0.1", port: int = DEFAULT_HTTP_PORT) -> None:
    lock_path = lock_file_for_port(port)
    clear_stale_single_instance_lock(lock_path)
    if not acquire_single_instance_lock(lock_path):
        print(f"Another server instance is already running in this project ({lock_path}).")
        print(f"Auto-quote project folder: {ROOT}")
        print("Stop that Python process, or exit the Cursor/IDE terminal that's running server.py.")
        print("If the old process crashed, exit any stuck Python holding this lock, then delete .server.lock manually.")
        return

    server = None
    admin_server = None
    try:
        try:
            init_quote_storage()
            server = ThreadingHTTPServer((host, port), QuoteHandler)
            setattr(server, "_quote_site", "front")
        except OSError as error:
            if is_port_in_use_error(error):
                print(f"Port {port} is already in use.")
                sug = port + 1
                print(f"Try another port, e.g.: python server.py {sug}")
                print("Or stop the old instance that is binding this port.")
                return
            raise

        admin_port = resolved_admin_listen_port()
        admin_host = resolved_admin_listen_host()
        if admin_port > 0:
            try:
                admin_server = ThreadingHTTPServer((admin_host, admin_port), QuoteHandler)
                setattr(admin_server, "_quote_site", "admin")
                threading.Thread(
                    target=admin_server.serve_forever,
                    daemon=True,
                    name="admin-site-http",
                ).start()
                print(f"[报价归档后台·独立端口] http://{admin_host}:{admin_port}/admin/login")
                print(f"[后台 API 前缀] http://{admin_host}:{admin_port}/admin-api/")
                allow_ips = os.environ.get("QUOTE_ADMIN_ALLOW_IPS", "").strip()
                if allow_ips:
                    print(f"[后台加固] QUOTE_ADMIN_ALLOW_IPS={allow_ips}")
            except OSError as err:
                print(f"[报价归档后台] 未启动（{admin_host}:{admin_port}）：{err}")
                admin_server = None

        print(f"[自动报价工作台·前台] http://{host}:{port}/")
        print(f"项目路径: {ROOT}")
        print("浏览器必须带端口（上面完整地址）；只输入 127.0.0.1 无效。")
        if host == "127.0.0.1":
            print(f"提示：若 http://localhost:{port}/ 打不开，请改用 http://127.0.0.1:{port}/（或反向尝试）。")
        threading.Thread(
            target=_warm_embedding_daemon,
            name="embedding-warm",
            daemon=True,
        ).start()
        threading.Thread(
            target=_pending_auto_learn_daemon,
            name="knowledge-auto-apply",
            daemon=True,
        ).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped by user.")
    finally:
        if admin_server is not None:
            try:
                admin_server.shutdown()
            except Exception:
                pass
            try:
                admin_server.server_close()
            except Exception:
                pass
        if server is not None:
            server.server_close()
        release_single_instance_lock()


def is_port_in_use_error(error: OSError) -> bool:
    return error.errno in {
        errno.EADDRINUSE,
        10048,  # Windows WSAEADDRINUSE
    }


def has_effective_material_pricing(items: object) -> bool:
    if not isinstance(items, list) or not items:
        return False
    for row in items:
        if not isinstance(row, dict):
            continue
        amount_value = parse_numeric(row.get("amount"))
        if amount_value > 0:
            return True
        unit_price_value = parse_unit_price_numeric(row.get("unit_price"))
        if unit_price_value > 0:
            return True
    return False


def parse_numeric(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_unit_price_numeric(value: object) -> float:
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    if looks_like_quantity_ladder(text):
        return 0.0
    matched = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if matched is None:
        return 0.0
    try:
        return float(matched.group(0))
    except ValueError:
        return 0.0


def looks_like_quantity_ladder(text: str) -> bool:
    if "/" not in text and "\\" not in text and "," not in text and "，" not in text:
        return False
    if re.search(r"(qty|quantity|数量)", text):
        return True
    parts = [part.strip() for part in re.split(r"[\\/,\|，]+", text) if part.strip()]
    numeric_parts = [part for part in parts if re.fullmatch(r"\d+(?:\.\d+)?", part)]
    return len(numeric_parts) >= 2


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        k = ctypes.windll.kernel32
        q = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        h = k.OpenProcess(q, False, pid)
        if h:
            k.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def clear_stale_single_instance_lock(lock_path: Path) -> None:
    """进程异常退出时常留下锁文件；若其中 PID 已不存在则删除，避免永远无法启动。"""
    if not lock_path.is_file():
        return
    try:
        raw = lock_path.read_text(encoding="utf-8").strip().split()
        if not raw:
            lock_path.unlink(missing_ok=True)
            return
        owner = int(raw[0])
    except (OSError, ValueError):
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    if not _process_exists(owner):
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def acquire_single_instance_lock(lock_path: Path) -> bool:
    global _LOCK_HANDLE
    if _LOCK_HANDLE is not None:
        return True

    handle = lock_path.open("a+", encoding="utf-8")
    try:
        handle.seek(0)
        handle.write(" ")
        handle.flush()
        handle.seek(0)

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    _LOCK_HANDLE = handle
    atexit.register(release_single_instance_lock)
    return True


def release_single_instance_lock() -> None:
    global _LOCK_HANDLE
    if _LOCK_HANDLE is None:
        return

    try:
        _LOCK_HANDLE.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_LOCK_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        _LOCK_HANDLE.close()
        _LOCK_HANDLE = None


def resolved_listen_port() -> int:
    """命令行优先级高于环境变量，其次为默认端口（见 DEFAULT_HTTP_PORT）。"""
    raw = (
        sys.argv[1].strip()
        if len(sys.argv) > 1 and str(sys.argv[1]).strip().isdigit()
        else ""
    )
    if raw:
        return int(raw)
    for key in ("QUOTE_SERVER_PORT", "SERVER_PORT"):
        env_val = os.environ.get(key, "").strip()
        if env_val.isdigit():
            return int(env_val)
    return DEFAULT_HTTP_PORT


def resolved_listen_host() -> str:
    raw = os.environ.get("QUOTE_SERVER_HOST", "").strip()
    return raw if raw else "127.0.0.1"


def resolved_admin_listen_port() -> int:
    raw = os.environ.get("QUOTE_ADMIN_HTTP_PORT", str(DEFAULT_ADMIN_HTTP_PORT)).strip().lower()
    if raw in ("0", "", "off", "false", "no", "none"):
        return 0
    if raw.isdigit():
        return int(raw)
    try:
        return int(DEFAULT_ADMIN_HTTP_PORT)
    except (TypeError, ValueError):
        return DEFAULT_ADMIN_HTTP_PORT


def resolved_admin_listen_host() -> str:
    raw = os.environ.get("QUOTE_ADMIN_SERVER_HOST", "").strip()
    return raw if raw else "127.0.0.1"


if __name__ == "__main__":
    force_unlock_args = {"--force-unlock", "--force_unlock"}
    if any(arg in sys.argv for arg in force_unlock_args):
        sys.argv[:] = [a for a in sys.argv if a not in force_unlock_args]
        lock_path_rm = lock_file_for_port(resolved_listen_port())
        try:
            lock_path_rm.unlink(missing_ok=True)
            print(f"Removed lock file ({lock_path_rm}). Retrying startup…")
        except OSError as err:
            print(f"Unable to delete lock file: {err}")
            print("Quit any Python holding this project's server.py or reboot, then retry.")
            sys.exit(1)
    run(host=resolved_listen_host(), port=resolved_listen_port())
