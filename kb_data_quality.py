"""知识库/价格库新增前的数据质量判断。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from material_row_validity import (
    RECOGNITION_CANDIDATE,
    RECOGNITION_IGNORED,
    RECOGNITION_SPLIT,
    STRONG_MATERIAL_HINTS,
    classify_material_row,
    is_ignored_material_text,
    is_part_description_candidate,
)
from sheet_parser import contains_any, normalize_text, should_drop_upload_name

KB_ACTION_AUTO = "auto_insert"
KB_ACTION_REVIEW = "pending_review"
KB_ACTION_DROP = "drop"

_GARBAGE_SYMBOL_RX = re.compile(r"[?？]")
_GARBAGE_FRAGMENT_RX = re.compile(
    r"^(?:侧面的主面|侧.?主面|主面[）)]?$|外.?主面|里.?主面|内侧.?$|外侧.?$)",
    re.I,
)
_BLOCKED_NAME_TOKENS = ("合计", "小计", "系统成本", "加工费", "杂费", "管理费", "开模", "模具", "系统估算")
_PIECE_OR_NON_MATERIAL_NAMES = frozenset(
    {
        "前片",
        "后片",
        "底片",
        "侧片",
        "侧片（2片）",
        "拉链弧形盖",
        "前袋",
        "网袋",
        "隔层",
        "侧袋",
        "背垫",
        "提手",
    }
)
_NON_MATERIAL_NAME_MARKERS = ("推理待核", "系统估算", "AI估算", "推断", "结构/图片推理", "待确认")
_SUSPICIOUS_UNIT_RX = re.compile(r"^\d+(?:\.\d+)?(?:/|元)?$")


@dataclass(frozen=True)
class KbDataQualityVerdict:
    action: str
    reason: str
    tier: str  # trusted | suspicious | garbage

    @property
    def is_auto_insert(self) -> bool:
        return self.action == KB_ACTION_AUTO

    @property
    def is_review(self) -> bool:
        return self.action == KB_ACTION_REVIEW

    @property
    def is_drop(self) -> bool:
        return self.action == KB_ACTION_DROP


def _has_garbage_symbol(*values: object) -> bool:
    return any(_GARBAGE_SYMBOL_RX.search(str(value or "")) for value in values)


def _looks_like_garbage_fragment(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    if _GARBAGE_FRAGMENT_RX.search(text):
        return True
    normalized = normalize_text(text)
    if len(normalized) <= 10 and contains_any(normalized, ("侧面", "主面", "外侧", "内侧", "说明")):
        if not any(ch in text for ch in ("扣", "链", "带", "布", "料", "zip", "fabric")):
            return True
    return False


def _is_piece_or_structure_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    if text in _PIECE_OR_NON_MATERIAL_NAMES:
        return True
    if any(marker in text for marker in _NON_MATERIAL_NAME_MARKERS):
        return True
    normalized = normalize_text(text)
    if contains_any(
        normalized,
        ("前片", "后片", "底片", "侧片", "拉链弧形", "部位", "裁片", "排刀", "用量公式"),
    ):
        if not contains_any(normalized, STRONG_MATERIAL_HINTS):
            return True
    return False


def _blocked_material_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text or text in {"-", "—", "/"}:
        return True
    if any(token in text for token in _BLOCKED_NAME_TOKENS):
        return True
    return should_drop_upload_name(text)


def _has_usable_price(price: str) -> bool:
    from price_admin_store import _has_usable_price as check

    return check(price)


def _row_price_needs_human_review(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    from price_admin_store import _row_price_needs_human_review as check

    return check(row)


def _looks_like_trusted_material_identity(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    ignored, _ = is_ignored_material_text(text)
    if ignored:
        return False
    if _looks_like_garbage_fragment(text):
        return False
    compact = text.replace(" ", "")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-\./#]*", compact):
        return True
    normalized = normalize_text(text)
    if contains_any(normalized, STRONG_MATERIAL_HINTS):
        return True
    if any(ch in text for ch in ("扣", "链", "带", "布", "料", "尼龙", "涤纶", "纱", "线")):
        return True
    if re.search(r"\d+\s*[DdT]", text):
        return True
    return 2 <= len(text) <= 24


def _recognition_blocks_auto(row: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(row, dict):
        return False, ""
    status = str(row.get("recognition_status") or "").strip()
    if status == RECOGNITION_IGNORED:
        return True, str(row.get("recognition_reason") or "识别为无效物料")
    if status in {RECOGNITION_CANDIDATE, RECOGNITION_SPLIT} and not bool(row.get("recognition_confirmed")):
        reason = str(row.get("recognition_reason") or "待人工确认后再入库")
        return True, reason
    if bool(row.get("exclude_from_cost")) and not bool(row.get("recognition_confirmed")):
        return True, "未确认参与报价，暂不入正式库"
    return False, ""


def judge_kb_insert_candidate(
    name: str,
    spec: str = "-",
    price: str = "",
    *,
    row: dict[str, Any] | None = None,
    kb_hit: bool = False,
) -> KbDataQualityVerdict:
    """新增知识库前的数据质量裁决。

    - auto_insert：合理可信的材料数据，可自动入库
    - pending_review：可疑/不完整，进异常表待人工确认
    - drop：明显垃圾，直接丢弃
    """
    material_name = str(name or "").strip()
    material_spec = str(spec or "").strip() or "-"
    material_price = str(price or "").strip()

    if _blocked_material_name(material_name):
        return KbDataQualityVerdict(KB_ACTION_DROP, "名称无效或为表头/汇总项", "garbage")
    if _is_piece_or_structure_name(material_name):
        return KbDataQualityVerdict(KB_ACTION_DROP, "裁片/部位/非材料行，不入库", "garbage")
    if _has_garbage_symbol(material_name, material_spec, material_price):
        return KbDataQualityVerdict(KB_ACTION_DROP, "含无法识别的乱码符号", "garbage")
    if _looks_like_garbage_fragment(material_name):
        return KbDataQualityVerdict(KB_ACTION_DROP, "明显无业务意义的碎片文本", "garbage")

    is_part, part_reason = is_part_description_candidate(material_name)
    if is_part:
        return KbDataQualityVerdict(KB_ACTION_REVIEW, part_reason, "suspicious")

    ignored, ignore_reason = is_ignored_material_text(material_name)
    if ignored:
        return KbDataQualityVerdict(KB_ACTION_DROP, ignore_reason, "garbage")

    rec_blocked, rec_reason = _recognition_blocks_auto(row)
    if rec_blocked and str((row or {}).get("recognition_status") or "") == RECOGNITION_IGNORED:
        return KbDataQualityVerdict(KB_ACTION_DROP, rec_reason, "garbage")
    if rec_blocked:
        return KbDataQualityVerdict(KB_ACTION_REVIEW, rec_reason, "suspicious")

    status, class_reason = classify_material_row(material_name, kb_hit=kb_hit)
    if status == RECOGNITION_IGNORED:
        return KbDataQualityVerdict(KB_ACTION_DROP, class_reason, "garbage")

    has_price = _has_usable_price(material_price)
    needs_ai_review = _row_price_needs_human_review(row)

    if status == RECOGNITION_CANDIDATE:
        if not has_price:
            if material_spec in {"", "-", "—"} and not str((row or {}).get("usage") or "").strip():
                return KbDataQualityVerdict(
                    KB_ACTION_REVIEW,
                    "缺少单价且规格/用量信息不足，待人工补全",
                    "suspicious",
                )
            return KbDataQualityVerdict(
                KB_ACTION_REVIEW,
                "疑似新材料但缺少可信单价，待人工确认",
                "suspicious",
            )
        if not needs_ai_review and _looks_like_trusted_material_identity(material_name):
            pass
        else:
            return KbDataQualityVerdict(KB_ACTION_REVIEW, class_reason, "suspicious")

    if not has_price:
        if material_spec in {"", "-", "—"} and not str((row or {}).get("usage") or "").strip():
            return KbDataQualityVerdict(
                KB_ACTION_REVIEW,
                "缺少单价且规格/用量信息不足，待人工补全",
                "suspicious",
            )
        return KbDataQualityVerdict(
            KB_ACTION_REVIEW,
            "疑似新材料但缺少可信单价，待人工确认",
            "suspicious",
        )

    if needs_ai_review:
        return KbDataQualityVerdict(
            KB_ACTION_REVIEW,
            "单价来自 AI/系统估算，需人工确认后再正式入库",
            "suspicious",
        )

    if len(material_name) > 48:
        return KbDataQualityVerdict(KB_ACTION_REVIEW, "命名过长或疑似混合说明，待人工规范", "suspicious")

    if _SUSPICIOUS_UNIT_RX.fullmatch(material_price.replace(" ", "")):
        return KbDataQualityVerdict(KB_ACTION_REVIEW, "单价格式缺少单位，待人工确认", "suspicious")

    if kb_hit or str((row or {}).get("source") or "").strip().lower() == "kb":
        return KbDataQualityVerdict(KB_ACTION_AUTO, "知识库命中或来源可信", "trusted")

    return KbDataQualityVerdict(KB_ACTION_AUTO, "通过材料数据质量校验", "trusted")


def format_exception_reason_label(verdict: KbDataQualityVerdict, *, is_combined_split: bool = False) -> str:
    """将质量裁决映射为后台「异常原因」列的短标签。"""
    if is_combined_split:
        return "组合材料需拆分补价"
    reason = str(verdict.reason or "").strip()
    if "缺少单价" in reason or "缺少可信单价" in reason:
        return "缺少价格"
    if "规格" in reason and ("缺少" in reason or "不足" in reason):
        return "规格缺失"
    if "单价格式" in reason or "缺少单位" in reason:
        return "价格格式异常"
    if "AI" in reason or "系统估算" in reason:
        return "AI单价需确认"
    if "混合" in reason or "部件说明" in reason or "命名过长" in reason:
        return "名称疑似非材料"
    if "待人工确认" in reason or "未命中知识库" in reason:
        return "名称待人工确认"
    if verdict.tier == "suspicious":
        return reason[:24] if reason else "待人工确认"
    return reason[:24] if reason else "待人工确认"


def classify_exception_review_hint(
    name: str,
    verdict: KbDataQualityVerdict,
    *,
    has_price: bool = False,
    is_combined_split: bool = False,
) -> str:
    """异常队列处理建议：fixable=建议修正入库，exclude_suggest=建议排除，review=一般复核。"""
    if is_combined_split or (has_price and verdict.action == KB_ACTION_REVIEW):
        if any(token in str(verdict.reason or "") for token in ("AI", "系统估算", "单价格式", "缺少单位")):
            return "fixable"
    reason = str(verdict.reason or "")
    if any(token in reason for token in ("说明", "不作为物料", "无效", "噪声", "碎片")):
        return "exclude_suggest"
    if "混合" in reason or "部件说明" in reason or "命名过长" in reason:
        return "exclude_suggest"
    if not has_price or any(token in reason for token in ("缺少", "格式", "分摊", "AI", "系统估算")):
        return "fixable"
    text = str(name or "").strip()
    if len(text) <= 4 and not any(ch in text for ch in ("扣", "链", "带", "布", "料")):
        return "exclude_suggest"
    return "review"
