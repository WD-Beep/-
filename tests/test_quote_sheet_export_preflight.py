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

    def test_sample_fee_rejects_zero_and_empty(self) -> None:
        self.assertIn("function isSampleFeeFilled", self.js)
        fee_body = _extract_function_body("isSampleFeeFilled", self.js)
        self.assertIn("parseMoneyNumber", fee_body)
        self.assertIn("<= 0", fee_body)

    def test_sync_preflight_collects_all_required_fields(self) -> None:
        sync_body = _extract_function_body("collectExportMissingFieldsSync", self.js)
        self.assertIn("inspectPayeeForExportSync()", sync_body)
        self.assertIn("inspectSampleFieldsForExport()", sync_body)
        self.assertIn("inspectCustNameForExport()", sync_body)
        self.assertIn("inspectProductRowsForExport()", sync_body)
        self.assertIn("inspectQuoteCurrencyForExport", sync_body)

    def test_sync_preflight_formats_missing_summary(self) -> None:
        body = _extract_function_body("formatExportMissingSummary", self.js)
        self.assertIn("请先补充：", body)
        self.assertIn("shortLabel", body)

    def test_sync_preflight_failure_alerts_and_focuses(self) -> None:
        body = _extract_function_body("handleExportSyncPreflightFailure", self.js)
        self.assertIn("window.alert", body)
        self.assertIn("focusFirstMissingField", body)
        self.assertIn("quoteSheetStatus", body)

    def test_export_by_scope_runs_sync_before_any_await(self) -> None:
        body = _extract_function_body("exportByScope", self.js)
        sync_pos = body.index("runExportSyncPreflight")
        await_pos = body.index("await ")
        self.assertLess(sync_pos, await_pos)

    def test_export_pdf_sets_loading_before_async_body(self) -> None:
        export_pdf = _extract_function_body("exportPdf", self.js)
        sync_pos = export_pdf.index("runExportSyncPreflight")
        loading_pos = export_pdf.index("setExportButtonsLoading(true)")
        body_pos = export_pdf.index("runExportPdfBody")
        inflight_pos = export_pdf.index("exportGuard.inflight = true")
        self.assertLess(sync_pos, inflight_pos)
        self.assertLess(inflight_pos, loading_pos)
        self.assertLess(loading_pos, body_pos)

    def test_export_pdf_sync_failure_skips_network_body(self) -> None:
        export_pdf = _extract_function_body("exportPdf", self.js)
        self.assertIn("handleExportSyncPreflightFailure", export_pdf)
        failure_pos = export_pdf.index("handleExportSyncPreflightFailure")
        body_pos = export_pdf.index("runExportPdfBody")
        self.assertLess(failure_pos, body_pos)

    def test_all_required_missing_types_defined(self) -> None:
        for key in (
            "payee_company",
            "sample_fee",
            "sample_lead_time",
            "cust_name",
            "product_rows",
            "quote_currency",
        ):
            self.assertIn(key, self.js)
        self.assertIn("shortLabel", self.js)
        self.assertIn("收款账户", self.js)
        self.assertIn("打样费", self.js)
        self.assertIn("客户名称", self.js)

    def test_ensure_export_preflight_uses_sync_validation(self) -> None:
        body = _extract_function_body("ensureExportPreflight", self.js)
        self.assertIn("runExportSyncPreflight", body)
        self.assertIn("handleExportSyncPreflightFailure", body)
        self.assertNotIn("showExportPreflightDialog", body)

    def test_export_guard_blocks_duplicate_primary_export(self) -> None:
        export_pdf = _extract_function_body("exportPdf", self.js)
        self.assertIn("exportGuard.inflight", export_pdf)
        self.assertRegex(export_pdf, r"exportGuard\.inflight")

    def test_export_pdf_awaits_pdf_worker_before_releasing_guard(self) -> None:
        body = _extract_function_body("runExportPdfBody", self.js)
        self.assertIn("await worker", body)

    def test_chained_lang_export_skips_preflight_guard(self) -> None:
        self.assertIn("preflightSkipped: true", self.js)

    def test_export_pdf_skips_payee_language_blocking(self) -> None:
        body = _extract_function_body("runExportPdfBody", self.js)
        self.assertNotIn("ensurePayeeLanguageReadyForExport", body)

    def test_payee_searching_is_not_treated_as_ready(self) -> None:
        body = _extract_function_body("inspectPayeeForExportSync", self.js)
        self.assertIn("payeeState.searching", body)
        searching_block = body[body.index("payeeState.searching") :]
        self.assertIn("missingKey", searching_block)
        self.assertNotIn("ok: true", searching_block[: searching_block.index("return")])

    def test_set_export_buttons_loading_disables_both_buttons(self) -> None:
        body = _extract_function_body("setExportButtonsLoading", self.js)
        self.assertIn("qsExportPdfBtn", body)
        self.assertIn("qsExportPdfFobUsdBtn", body)
        self.assertIn("正在生成 PDF", body)

    def test_missing_payee_company_blocks_export_sync(self) -> None:
        body = _extract_function_body("inspectPayeeForExportSync", self.js)
        self.assertIn('missingKey: "payee_company"', body)
        sync_body = _extract_function_body("collectExportMissingFieldsSync", self.js)
        self.assertIn("inspectPayeeForExportSync()", sync_body)
        export_pdf = _extract_function_body("exportPdf", self.js)
        failure_pos = export_pdf.index("handleExportSyncPreflightFailure")
        body_pos = export_pdf.index("runExportPdfBody")
        self.assertLess(failure_pos, body_pos)

    def test_missing_sample_fee_blocks_export_sync(self) -> None:
        sample_body = _extract_function_body("inspectSampleFieldsForExport", self.js)
        self.assertIn('"sample_fee"', sample_body)
        sync_body = _extract_function_body("collectExportMissingFieldsSync", self.js)
        self.assertIn("inspectSampleFieldsForExport()", sync_body)

    def test_multiple_missing_fields_summarized_together(self) -> None:
        body = _extract_function_body("formatExportMissingSummary", self.js)
        self.assertIn("join(", body)
        self.assertIn("、", body)
        self.assertIn("seen", body)
        failure = _extract_function_body("handleExportSyncPreflightFailure", self.js)
        self.assertIn("formatExportMissingSummary", failure)

    def test_foreign_payee_missing_swift_does_not_block_sync(self) -> None:
        body = _extract_function_body("inspectPayeeForExportSync", self.js)
        self.assertNotIn('missingKey: "payee_swift"', body)

    def test_complete_export_sets_inflight_and_loading_before_html2pdf(self) -> None:
        export_pdf = _extract_function_body("exportPdf", self.js)
        inflight_pos = export_pdf.index("exportGuard.inflight = true")
        loading_pos = export_pdf.index("setExportButtonsLoading(true)")
        body_pos = export_pdf.index("runExportPdfBody")
        self.assertLess(inflight_pos, loading_pos)
        self.assertLess(loading_pos, body_pos)
        run_body = _extract_function_body("runExportPdfBody", self.js)
        confirm_pos = run_body.index("window.confirm")
        html2pdf_pos = run_body.index("html2pdf")
        self.assertLess(confirm_pos, html2pdf_pos)
        finally_pos = export_pdf.index("setExportButtonsLoading(false)")
        self.assertLess(body_pos, finally_pos)

    def test_export_by_scope_click_entry_is_sync_preflight(self) -> None:
        body = _extract_function_body("exportByScope", self.js)
        self.assertRegex(body, r"runExportSyncPreflight\(\{ asFobUsdPdf \}\)")
        self.assertIn("handleExportSyncPreflightFailure", body)


if __name__ == "__main__":
    unittest.main()
