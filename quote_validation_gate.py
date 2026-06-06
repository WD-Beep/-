"""报价输出闸门：风险分级（低/中/高）。高风险须人工确认后才放行最终价；中风险自动放行并审计。
环境变量 ``QUOTE_DISABLE_PRICING_GATE=1``（等）时可关闭工作台「核对解锁」「数据提醒」阻塞（单机自用）。见 ``pricing_gate_confirmation_bypassed``。
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from typing import Any

from bag_quote_costing import annotate_bag_cost_rows, enrich_pricing_gate_for_bag_quote
from quote_engine import (
    normalize_source,
    raw_unit_dimension_mismatch_hints,
    row_amount_crosscheck_hint,
    row_unit_dimension_mismatch_from_kinds,
    _price_unit_kind,
    _usage_unit_kind,
)

AI_CONFIDENCE_THRESHOLD_DEFAULT = 0.75
AI_MEDIUM_RISK_THRESHOLD_DEFAULT = 0.82


def ai_confidence_threshold() -> float:
    raw = os.environ.get("QUOTE_AI_CONFIDENCE_THRESHOLD", "").strip()
    if not raw:
        return AI_CONFIDENCE_THRESHOLD_DEFAULT
    try:
        v = float(raw)
        return v if 0 < v <= 1 else AI_CONFIDENCE_THRESHOLD_DEFAULT
    except (TypeError, ValueError):
        return AI_CONFIDENCE_THRESHOLD_DEFAULT


def pricing_gate_confirmation_bypassed() -> bool:
    """为 true 时：不阻塞最终价/PDF（等同始终「已核对」），并清空顶栏「数据提醒」文案。"""
    raw = os.environ.get("QUOTE_DISABLE_PRICING_GATE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def ai_medium_risk_threshold() -> float:
    raw = os.environ.get("QUOTE_AI_MEDIUM_RISK_THRESHOLD", "").strip()
    if not raw:
        return AI_MEDIUM_RISK_THRESHOLD_DEFAULT
    try:
        v = float(raw)
        return v if 0 < v <= 1 else AI_MEDIUM_RISK_THRESHOLD_DEFAULT
    except (TypeError, ValueError):
        return AI_MEDIUM_RISK_THRESHOLD_DEFAULT


def _row_ai_filled(row: dict[str, Any]) -> bool:
    """真实 AI/业务补全；纯展示推断（_spec/_usage_display_inferred）不参与风险闸门。"""
    return bool(
        row.get("ai_filled")
        or (row.get("spec_ai") and not row.get("_spec_display_inferred"))
        or (row.get("usage_ai") and not row.get("_usage_display_inferred"))
        or row.get("unit_price_ai")
        or row.get("amount_ai")
    )


def _ai_filled_field_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    if row.get("spec_ai") and not row.get("_spec_display_inferred"):
        keys.append("spec")
    if row.get("usage_ai") and not row.get("_usage_display_inferred"):
        keys.append("usage")
    if row.get("unit_price_ai"):
        keys.append("unit_price")
    if row.get("amount_ai"):
        keys.append("amount")
    return keys


def _data_origin_label(row: dict[str, Any]) -> str:
    if row.get("manual_row"):
        return "人工"
    st = str(row.get("source_type") or "").strip()
    if st == "user_explicit":
        return "用户输入"
    if st == "image_inferred":
        return "图片推断"
    src = normalize_source(row.get("source"))
    return "知识库" if src == "kb" else "AI"


def _price_text_missing(unit_price_raw: Any) -> bool:
    p = str(unit_price_raw or "").strip()
    return p in {"", "-", "—", "无", "待定", "待填", "n/a", "na", "NA"}


def _usage_text_missing(usage_raw: Any) -> bool:
    u = str(usage_raw or "").strip()
    if u in {"", "-", "—"}:
        return True
    return not bool(re.search(r"\d", u))


def _is_pure_fee_row(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return True
    fee_like = ("运费", "快递费", "版费", "模具费摊销", "摊销", "杂费汇总", "税金", "管理费单列")
    if any(k in n for k in fee_like):
        return True
    if re.match(r"^包装\s*$", n):
        return True
    return False


def _is_main_material_row(name: str) -> bool:
    """主料 / 大面积面料类（缺失用量视为高风险）。"""
    n = str(name or "").strip()
    if not n or _is_pure_fee_row(n):
        return False
    keys = (
        "主料",
        "外料",
        "面料",
        "牛津",
        "尼龙布",
        "尼龙格子",
        "格子布",
        "涤塔夫",
        "塔丝隆",
        "帆布",
        "无纺布",
        "DCF",
        "粗苯",
        "Ultra",
        "外布",
        "袋身主料",
        "围布",
    )
    return any(k in n for k in keys)


def _needs_core_unit_price_row(row: dict[str, Any]) -> bool:
    """核心物料行：需要有效单价（排除纯费用行）。"""
    name = str(row.get("name") or "").strip()
    if not name or _is_pure_fee_row(name):
        return False
    # 允许少量描述性辅料仍要求单价；结构类「图片 / 说明」行在上游已过滤
    return True


def _generic_calc_irreconcilable(note_raw: Any) -> bool:
    """计算方式占位 / 无法作为回算依据。"""
    t = str(note_raw or "").strip().lower()
    if not t:
        return False
    needles = (
        "未见「计算方式」",
        "数据源不含「计算方式」",
        "用量为 ai 估计",
        "用量为 ai 估算",
        "本条用量为 ai 估算",
        "构件分项未载入",
        "用量为 ai 估计",
        "ai 估算",
        "无法完成材料试算",
    )
    return any(x.lower() in t for x in needles)


def _accuracy_hints_irreconcilable(row: dict[str, Any]) -> bool:
    hints = row.get("accuracy_hints") or []
    if not isinstance(hints, list):
        return False
    blob = " ".join(str(h) for h in hints if isinstance(h, str))
    return ("粗略验算" in blob) or ("语义需人工核对" in blob and "口径" in blob)


def _calc_conflict_or_irreconcilable(row: dict[str, Any]) -> bool:
    if _accuracy_hints_irreconcilable(row):
        return True
    note = row.get("calc_note") or row.get("calc_method") or ""
    if _generic_calc_irreconcilable(note):
        # 占位文案 + AI 用量/单价更易出错 → 高风险；纯 KB 且无 AI 触碰则降为中等交由 reconciliation，此处不与 HIGH 强行等同
        if (
            _row_ai_filled(row)
            or (row.get("usage_ai") and not row.get("_usage_display_inferred"))
            or row.get("unit_price_ai")
        ):
            return True
    cross = row_amount_crosscheck_hint(
        row.get("usage"),
        row.get("unit_price"),
        float(row.get("amount") or 0.0),
    )
    return bool(cross and "粗略验算" in str(cross))


def _checkpoint_medium_signals(checkpoints: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    codes: list[str] = []
    for cp in checkpoints:
        if not isinstance(cp, dict):
            continue
        gap = cp.get("gap_pc")
        ref = cp.get("ref_cost_before_margin_pc")
        try:
            g = float(gap)
            r = float(ref) if ref is not None else 0.0
        except (TypeError, ValueError):
            continue
        ag = abs(g)
        if ag >= max(38.0, abs(r) * 0.12):
            codes.append(f"sheet_checkpoint_qty_{cp.get('quantity')}:gap={round(g, 2)}")
        qgap = cp.get("gap_exw_quote_pc")
        if qgap is not None:
            try:
                qg = abs(float(qgap))
            except (TypeError, ValueError):
                continue
            if qg >= 25.0:
                codes.append(f"sheet_exw_mismatch_qty_{cp.get('quantity')}")
    return bool(codes), codes


def _anchor_medium_signal(cost_bridge: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(cost_bridge, dict):
        return False, ""
    gap = cost_bridge.get("sheet_anchor_vs_computed_material_gap")
    anchor = cost_bridge.get("sheet_anchor_material_subtotal")
    if gap is None or anchor is None:
        return False, ""
    try:
        g = abs(float(gap))
        a = abs(float(anchor))
    except (TypeError, ValueError):
        return False, ""
    if g >= max(12.0, a * 0.07):
        return True, "sheet_material_anchor_gap"
    return False, ""


def _row_unit_conflict_hints(row: dict[str, Any], payload_row: dict[str, Any] | None = None) -> list[str]:
    """单位冲突：基于原始口径与单位维度判断，换算成功也不降级风险。"""
    converted = bool(row.get("unit_converted"))
    if not converted:
        calc = str(row.get("calc_note") or row.get("calc_method") or row.get("unit_conversion_basis") or "")
        converted = "单位换算" in calc

    usage_kind = row.get("usage_unit_kind")
    price_kind = row.get("price_unit_kind")
    if isinstance(payload_row, dict):
        if not usage_kind:
            usage_kind = _usage_unit_kind(payload_row.get("usage"))
        if not price_kind:
            price_kind = _price_unit_kind(payload_row.get("unit_price"))

    hints = row_unit_dimension_mismatch_from_kinds(usage_kind, price_kind, converted=converted)
    if hints:
        return hints

    raw_usage = row.get("raw_usage")
    raw_price = row.get("raw_unit_price")
    if isinstance(payload_row, dict):
        raw_usage = raw_usage or payload_row.get("usage")
        raw_price = raw_price or payload_row.get("unit_price")
    raw_usage = raw_usage or row.get("usage")
    raw_price = raw_price or row.get("unit_price")

    hints = raw_unit_dimension_mismatch_hints(raw_usage, raw_price, converted=converted)
    if hints:
        return hints

    return raw_unit_dimension_mismatch_hints(row.get("usage"), row.get("unit_price"), converted=False)


def apply_pricing_gate(
    result: dict[str, Any],
    payload: dict[str, Any],
    *,
    manual_confirmed: bool,
    confirmed_by: str | None = None,
) -> None:
    """写入 pricing_gate / pricing_audit / estimated_pricing（高风险未放行时）。"""
    thr_hard = ai_confidence_threshold()
    thr_medium = ai_medium_risk_threshold()

    rows = result.get("detail_rows")
    if not isinstance(rows, list):
        rows = []

    high_codes: list[str] = []
    unit_conflict_rows = 0
    min_conf_observed = 1.0
    ai_any = False
    ai_filled_summary: list[dict[str, Any]] = []

    payload_items = payload.get("items") if isinstance(payload.get("items"), list) else []

    out_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        r = dict(row)
        payload_row = payload_items[idx] if idx < len(payload_items) else None
        hints = _row_unit_conflict_hints(r, payload_row if isinstance(payload_row, dict) else None)
        origin = _data_origin_label(r)
        r["data_origin_label"] = origin

        row_high_flags: list[str] = []

        if hints:
            r["validation_status"] = "UNIT_CONFLICT"
            r["validation_detail"] = " ".join(hints)[:500]
            high_codes.append("unit_usage_price_conflict")
            unit_conflict_rows += 1
            row_high_flags.append("unit_usage_price_conflict")
        else:
            name = str(r.get("name") or "").strip()
            usage_missing_main = _is_main_material_row(name) and _usage_text_missing(r.get("usage"))
            price_missing_core = _needs_core_unit_price_row(r) and _price_text_missing(r.get("unit_price"))
            calc_bad = _calc_conflict_or_irreconcilable(r)

            if usage_missing_main:
                high_codes.append("main_material_usage_missing")
                row_high_flags.append("main_material_usage_missing")
                r["validation_status"] = "HIGH_RISK"
                r["validation_detail"] = "主料/面料类用量缺失"
            elif price_missing_core:
                high_codes.append("core_unit_price_missing")
                row_high_flags.append("core_unit_price_missing")
                r["validation_status"] = "HIGH_RISK"
                r["validation_detail"] = "核心物料单价缺失"
            elif calc_bad:
                high_codes.append("calc_irreconcilable")
                row_high_flags.append("calc_irreconcilable")
                r["validation_status"] = "HIGH_RISK"
                r["validation_detail"] = "计算方式无法可靠回算或与用量×单价不一致"
            elif _usage_text_missing(r.get("usage")) or _price_text_missing(r.get("unit_price")):
                r["validation_status"] = "INCOMPLETE"
                r["validation_detail"] = "用量或单价缺失（非主料硬性规则）"
            else:
                r["validation_status"] = "OK"
                r["validation_detail"] = ""

        if row_high_flags:
            r["risk_flags"] = row_high_flags

        filled = _row_ai_filled(r)
        if filled:
            ai_any = True
            try:
                c = float(r.get("ai_confidence", thr_hard))
            except (TypeError, ValueError):
                c = thr_hard
            c = max(0.0, min(1.0, c))
            min_conf_observed = min(min_conf_observed, c)
            fk = _ai_filled_field_keys(r)
            if fk:
                ai_filled_summary.append(
                    {
                        "row_index": idx,
                        "material_name": str(r.get("name") or "")[:120],
                        "fields": fk,
                        "ai_confidence": round(c, 4),
                    }
                )

        out_rows.append(r)

    structure_text = str(
        payload.get("structure_text_snapshot") or payload.get("structure_text") or ""
    ).strip()
    try:
        from structure_gap_hints import (
            build_anomaly_review_hints,
            build_structure_gap_hints,
            enrich_row_ambiguous_classification,
            merge_gap_hints_into_data_notice,
        )

        out_rows = [
            enrich_row_ambiguous_classification(r, context=structure_text)
            if isinstance(r, dict)
            else r
            for r in out_rows
        ]
        gap_hints = payload.get("structure_gap_hints")
        if not isinstance(gap_hints, list) or not gap_hints:
            gap_hints = build_structure_gap_hints(
                structure_text,
                out_rows,
                demand_template=bool(payload.get("demand_template")),
            )
        if gap_hints:
            result["structure_gap_hints"] = gap_hints
            result["data_notice"] = merge_gap_hints_into_data_notice(
                str(result.get("data_notice") or ""),
                gap_hints,
            )
        try:
            mt = float(result.get("material_total") or 0)
        except (TypeError, ValueError):
            mt = None
        try:
            pf = float(payload.get("processing_fee") or 0)
        except (TypeError, ValueError):
            pf = None
        anomaly = build_anomaly_review_hints(
            items=out_rows,
            structure_text=structure_text,
            gap_hints=gap_hints if isinstance(gap_hints, list) else None,
            processing_fee=pf,
            material_total=mt,
        )
        if anomaly:
            result["anomaly_review_hints"] = anomaly
    except Exception:
        pass

    result["detail_rows"] = out_rows

    bag_gate = enrich_pricing_gate_for_bag_quote(result, payload)
    bag_high_codes = list(bag_gate.get("high_codes") or [])
    bag_report = bag_gate.get("report") if isinstance(bag_gate.get("report"), dict) else {}
    if bag_report.get("is_bag_product"):
        structure_text = str(
            payload.get("structure_text_snapshot") or payload.get("structure_text") or ""
        ).strip()
        result["detail_rows"] = annotate_bag_cost_rows(out_rows, structure_text=structure_text)

    ck_rows = result.get("sales_sheet_checkpoints")
    checkpoints = ck_rows if isinstance(ck_rows, list) else []
    sheet_med_flag, sheet_med_codes = _checkpoint_medium_signals(checkpoints)

    cb = result.get("cost_bridge")
    anchor_med_flag, anchor_med_code = _anchor_medium_signal(cb) if isinstance(cb, dict) else (False, "")

    high_reasons = sorted(set(high_codes))
    if result.get("bag_quote_review_required"):
        high_reasons = sorted(set(high_reasons + bag_high_codes))
    has_high = bool(high_reasons)

    medium_signals: list[str] = []
    if ai_any and min_conf_observed + 1e-9 < thr_medium:
        medium_signals.append("ai_confidence_below_medium_threshold")
    if sheet_med_flag:
        medium_signals.extend(sheet_med_codes)
    if anchor_med_flag and anchor_med_code:
        medium_signals.append(anchor_med_code)

    has_medium_signal = bool(medium_signals) and not has_high

    if has_high:
        risk_level = "HIGH"
    elif has_medium_signal:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    confirm_required = bool(has_high and not manual_confirmed)
    final_allowed = not confirm_required

    # confirmed_by：放行主体
    confirmed_actor: str | None = None
    if final_allowed:
        if manual_confirmed and has_high:
            confirmed_actor = confirmed_by or "session:user_confirm"
        elif risk_level == "MEDIUM":
            confirmed_actor = confirmed_by or "system:auto_medium_risk"
        else:
            confirmed_actor = confirmed_by or "system:auto_low_risk"

    pricing_output_mode = "estimated" if not final_allowed else "final"

    quote_gate_status = "NEED_CONFIRM" if confirm_required else "OK"

    hint_cn = ""
    if confirm_required and result.get("bag_quote_review_required"):
        hint_cn = (
            "包类报价需人工复核：结构模块覆盖不足、漏项或成本明显偏低。"
            "请核对肩带/外袋/辅料/工艺等是否齐全后再解锁。"
        )
    elif confirm_required:
        hint_cn = (
            "高风险：存在单位冲突、主料用量/核心单价缺失或计算方式无法可靠回算。"
            "请先核对明细并点击「已核对」解锁后，再生成报价单。"
        )
    elif risk_level == "MEDIUM":
        hint_cn = (
            "中风险：含模型补全或表内对账偏差信号，系统已自动放行最终价并已记入审计；"
            "建议仍人工复核明细。"
        )

    pricing_gate: dict[str, Any] = {
        "risk_level": risk_level,
        "quote_gate_status": quote_gate_status,
        "confirm_required": confirm_required,
        "confirmed_by": None if confirm_required else confirmed_actor,
        "final_price_allowed": final_allowed,
        "pricing_output_mode": pricing_output_mode,
        "high_risk_codes": high_reasons,
        "medium_risk_codes": sorted(set(medium_signals)) if risk_level == "MEDIUM" else [],
        "unit_conflict_rows": unit_conflict_rows,
        "ai_confidence": round(min_conf_observed, 4) if ai_any else None,
        "ai_filled_fields": ai_filled_summary,
        "ai_confidence_threshold_hard": thr_hard,
        "ai_medium_risk_threshold": thr_medium,
        "manual_confirmed_applied": bool(manual_confirmed),
        "hint_cn": hint_cn,
        # 兼容旧前端字段
        "blocking_codes": sorted(
            dict.fromkeys(high_reasons + (medium_signals if risk_level == "MEDIUM" else []))
        ),
        "min_ai_confidence_observed": round(min_conf_observed, 4) if ai_any else 1.0,
    }
    result["pricing_gate"] = pricing_gate

    audit = result.setdefault("pricing_audit", {})
    audit["risk_level"] = risk_level
    audit["ai_confidence"] = pricing_gate["ai_confidence"]
    audit["ai_filled_fields"] = copy.deepcopy(ai_filled_summary)
    audit["confirm_required"] = confirm_required
    audit["confirmed_by"] = None if confirm_required else confirmed_actor

    audit.setdefault("timeline", [])
    timeline_entry = {
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "risk_level": risk_level,
        "phase": pricing_output_mode,
        "final_price_allowed": final_allowed,
        "confirm_required": confirm_required,
        "confirmed_by": audit["confirmed_by"],
        "manual_confirmed": bool(manual_confirmed),
        "high_risk_codes": high_reasons,
        "medium_risk_codes": pricing_gate["medium_risk_codes"],
        "rows_ai_filled": sum(1 for r in out_rows if isinstance(r, dict) and _row_ai_filled(r)),
    }
    audit["timeline"].append(timeline_entry)
    audit["last_param_fingerprint"] = _payload_fingerprint(payload)
    audit["last_row_validation"] = [
        {
            "name": str(r.get("name") or "")[:80],
            "validation_status": r.get("validation_status"),
            "risk_flags": r.get("risk_flags"),
            "data_origin_label": r.get("data_origin_label"),
            "ai_filled": _row_ai_filled(r),
            "ai_confidence": r.get("ai_confidence"),
            "ai_reason": str(r.get("ai_reason") or "")[:240],
        }
        for r in out_rows
        if isinstance(r, dict)
    ]

    result.pop("estimated_pricing", None)
    if risk_level == "MEDIUM" and final_allowed:
        result["estimated_pricing"] = {
            "risk_level": "MEDIUM",
            "material_total": result.get("material_total"),
            "material_total_text": result.get("material_total_text"),
            "tiers": copy.deepcopy(result.get("tiers")),
            "system_cost_text": result.get("system_cost_text"),
            "notice_cn": "中风险镜像预估：数值与当前最终价一致，系统已自动放行并已审计；对外使用前建议复核。",
            "final_price_allowed": True,
        }
    elif not final_allowed:
        result["estimated_pricing"] = {
            "risk_level": "HIGH",
            "material_total": result.get("material_total"),
            "material_total_text": result.get("material_total_text"),
            "tiers": copy.deepcopy(result.get("tiers")),
            "system_cost_text": result.get("system_cost_text"),
            "notice_cn": "高风险预估：须人工确认解锁后方可作为最终对外口径。",
            "final_price_allowed": False,
        }

    # 工作台「不要解锁条 / 不要数据提醒」：仅环境变量开关，默认关闭（保持合规闸门）。
    if pricing_gate_confirmation_bypassed():
        pg = dict(result.get("pricing_gate") or {})
        pg["confirm_required"] = False
        pg["final_price_allowed"] = True
        pg["quote_gate_status"] = "OK"
        pg["pricing_output_mode"] = "final"
        pg["hint_cn"] = ""
        pg["confirmation_bypassed"] = True
        pg["confirmation_bypass_source"] = "QUOTE_DISABLE_PRICING_GATE"
        result["pricing_gate"] = pg
        aud = result.setdefault("pricing_audit", {})
        aud["confirm_required"] = False
        if not aud.get("confirmed_by"):
            aud["confirmed_by"] = "env:QUOTE_DISABLE_PRICING_GATE"
        result.pop("estimated_pricing", None)
        result["data_notice"] = ""


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    snap = {
        "qty": payload.get("quantities"),
        "items_len": len(payload.get("items") or []) if isinstance(payload.get("items"), list) else 0,
        "gm": payload.get("gross_margin_rate"),
    }
    try:
        return json.dumps(snap, ensure_ascii=False, sort_keys=True, default=str)[:400]
    except TypeError:
        return str(hash(str(snap)))
