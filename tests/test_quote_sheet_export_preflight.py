"""生成报价单导出前预检逻辑（源码契约断言）。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "static" / "quote_sheet.js"


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _extract_function_body(name: str, js: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(", js)
    if not match:
        raise AssertionError(f"unable to locate function: {name}")
    paren_start = match.end() - 1
    paren_depth = 0
    paren_end = -1
    for idx in range(paren_start, len(js)):
        ch = js[idx]
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
            if paren_depth == 0:
                paren_end = idx
                break
    if paren_end < 0:
        raise AssertionError(f"unable to parse function params: {name}")
    brace = js.index("{", paren_end)
    depth = 0
    for idx in range(brace, len(js)):
        ch = js[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[brace : idx + 1]
    raise AssertionError(f"unable to extract function body: {name}")


class QuoteSheetExportPreflightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read_js()

    def test_inspect_sample_fields_always_checks_fee_and_lead(self) -> None:
        body = _extract_function_body("inspectSampleFieldsForExport", self.js)
        self.assertIn("readSampleFeeFromForm()", body)
        self.assertIn("readSampleLeadTimeFromForm()", body)
        self.assertNotIn('readSampleRequiredFromForm() === "no"', body)

    def test_validate_before_export_collects_payee_and_sample_missing(self) -> None:
        body = _extract_function_body("validateBeforeExport", self.js)
        self.assertIn("inspectPayeeForExport()", body)
        self.assertIn("inspectSampleFieldsForExport()", body)
        self.assertIn("missingKeys.push", body)

    def test_all_three_missing_types_defined(self) -> None:
        self.assertIn("payee_company", self.js)
        self.assertIn("sample_fee", self.js)
        self.assertIn("sample_lead_time", self.js)
        self.assertIn("请先选择收款公司", self.js)
        self.assertIn("请填写打样费", self.js)
        self.assertIn("请填写打样时间", self.js)

    def test_complete_validation_skips_preflight_dialog(self) -> None:
        body = _extract_function_body("ensureExportPreflight", self.js)
        complete_pos = body.index("validation.complete")
        dialog_pos = body.index("showExportPreflightDialog")
        self.assertLess(complete_pos, dialog_pos)

    def test_export_guard_blocks_duplicate_primary_export(self) -> None:
        export_pdf = _extract_function_body("exportPdf", self.js)
        self.assertIn("exportGuard.inflight", export_pdf)
        self.assertRegex(export_pdf, r"if\s*\(\s*exportGuard\.inflight\s*\)")

    def test_preflight_dialog_singleton_promise(self) -> None:
        dialog_body = _extract_function_body("showExportPreflightDialog", self.js)
        self.assertIn("exportGuard.preflightDialogPromise", dialog_body)
        self.assertIn("if (exportGuard.preflightDialogPromise)", dialog_body)

    def test_return_fill_focuses_first_missing_field(self) -> None:
        body = _extract_function_body("ensureExportPreflight", self.js)
        self.assertIn('action === "fill"', body)
        self.assertIn("focusFirstMissingField(validation.missing[0])", body)

    def test_proceed_only_when_user_clicks_proceed(self) -> None:
        body = _extract_function_body("ensureExportPreflight", self.js)
        self.assertIn('action === "proceed"', body)

    def test_export_pdf_awaits_pdf_worker_before_releasing_guard(self) -> None:
        body = _extract_function_body("runExportPdfBody", self.js)
        self.assertIn("await worker", body)

    def test_chained_lang_export_skips_preflight_guard(self) -> None:
        self.assertIn("preflightSkipped: true", self.js)


if __name__ == "__main__":
    unittest.main()
