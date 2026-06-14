"""报价单导出前收款账户语言一致性校验（基于最终 PDF 字段，而非输入框原文）。"""
from __future__ import annotations

from typing import Any

from company_payment_accounts import classify_account_bucket


def validate_payee_account_type_consistency(
    export_lang: str,
    payee: dict[str, Any] | None,
    *,
    selected_bank_account_type: str = "",
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payee, dict):
        return issues
    bucket = str(selected_bank_account_type or payee.get("account_type") or "").strip().lower()
    payee_bucket = str(payee.get("account_type") or classify_account_bucket(payee)).strip().lower()
    if bucket and payee_bucket and bucket != payee_bucket:
        issues.append(
            {
                "key": "payee_account_type",
                "message": "所选收款公司与当前账户类型不一致，请重新选择。",
                "blocking": True,
            }
        )
    return issues


def validate_payee_swift_for_foreign(payee: dict[str, Any] | None) -> list[dict[str, Any]]:
    """SWIFT Code 为可选项：缺失时不阻止导出，PDF 中无 SWIFT 则省略该行。"""
    return []


def validate_payee_export_language_consistency(
    export_lang: str,
    payee: dict[str, Any] | None,
    *,
    payee_en: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """收款账户与导出语言不一致时不阻止导出；仅在校验收款公司是否已选。"""
    if not isinstance(payee, dict) or not str(payee.get("company_name") or "").strip():
        return [
            {
                "key": "payee_company",
                "message": "请先选择收款公司。",
                "blocking": True,
            }
        ]
    return []


def validate_quote_sheet_export_payload(
    *,
    export_lang: str,
    bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    bundle = bundle if isinstance(bundle, dict) else {}
    payee = bundle.get("payee") if isinstance(bundle.get("payee"), dict) else None
    selected_type = str(
        bundle.get("selected_bank_account_type")
        or bundle.get("payee_account_type")
        or ""
    ).strip().lower()
    payee_en = None
    lang = str(export_lang or "cn").strip().lower()
    if lang == "en" and payee:
        from quote_sheet_i18n import translate_quote_sheet_fields

        translated = translate_quote_sheet_fields(
            {
                "meta": bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {},
                "rows": [],
                "payee": payee,
            }
        )
        raw_en = translated.get("payee_en")
        payee_en = raw_en if isinstance(raw_en, dict) else None

    issues: list[dict[str, Any]] = []
    issues.extend(validate_payee_account_type_consistency(lang, payee, selected_bank_account_type=selected_type))
    issues.extend(validate_payee_export_language_consistency(lang, payee, payee_en=payee_en))
    issues.extend(validate_payee_swift_for_foreign(payee))
    blocking = [item for item in issues if item.get("blocking", True)]
    return {
        "ok": len(blocking) == 0,
        "export_lang": lang,
        "selected_bank_account_type": selected_type,
        "issues": issues,
        "blocking_issues": blocking,
    }
