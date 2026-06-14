"""报价单 PDF 顶部信息区布局（静态模板/CSS 断言）。"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QuoteSheetPdfLayoutTest(unittest.TestCase):
    def test_meta_right_column_left_aligned_in_css(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".qs-pdf-meta-right-shifted", css)
        block_start = css.index(".qs-pdf-meta-right-shifted")
        block = css[block_start : block_start + 420]
        self.assertIn("text-align: left", block)
        self.assertIn("transform: translateX(var(--qs-pdf-meta-right-shift-x))", block)
        self.assertNotIn("padding-right: 42%", block)
        self.assertIn("--qs-pdf-meta-right-left: 108mm", css)
        self.assertIn("--qs-pdf-meta-right-shift-x: 27mm", css)

    def test_doc_title_stays_centered(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        title_start = css.index(".qs-pdf-doc-title {")
        title_block = css[title_start : title_start + 220]
        self.assertIn("text-align: center", title_block)
        self.assertNotIn("padding-left: var(--qs-pdf-header-right-anchor)", title_block)

    def test_meta_labels_and_values_present_in_html(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-pdf-lbl="lbl_meta_quote_no"', html)
        self.assertIn('data-pdf-lbl="lbl_meta_email"', html)
        self.assertIn('data-pdf-lbl="lbl_meta_cust_phone"', html)
        self.assertIn("qs-pdf-meta-value", html)
        self.assertIn("邮箱：", html)
        self.assertIn("联系电话：", html)

    def test_quote_no_single_line_css(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".qs-pdf-meta-value-quote-no", css)
        block_start = css.index(".qs-pdf-meta-value-quote-no")
        block = css[block_start : block_start + 220]
        self.assertIn("white-space: nowrap", block)
        self.assertIn("text-overflow: ellipsis", block)
        self.assertIn('[data-pdf-lbl="lbl_meta_cust_phone"]', css)
        self.assertIn('[data-pdf-lbl="lbl_meta_quote_no"]', css)
        en_quote_no_lbl_start = css.index(
            '[data-pdf-lbl="lbl_meta_quote_no"]'
        )
        en_quote_no_lbl_block = css[en_quote_no_lbl_start : en_quote_no_lbl_start + 160]
        self.assertIn("min-width: 0", en_quote_no_lbl_block)
        self.assertIn("margin-right: 0.12em", en_quote_no_lbl_block)
        en_quote_no_start = css.index(
            '.qs-pdf-root[data-pdf-lang="en"] .qs-pdf-meta-right-shifted .qs-pdf-meta-value-quote-no'
        )
        en_quote_no_block = css[en_quote_no_start : en_quote_no_start + 160]
        self.assertIn("display: inline", en_quote_no_block)
        self.assertIn("max-width: none", en_quote_no_block)

    def test_sample_meta_fields_present_in_html(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="qsSampleRequired"', html)
        self.assertNotIn("是否需要打样", html)
        self.assertIn('id="qsSampleFee"', html)
        self.assertIn('id="qsSampleLeadTime"', html)
        self.assertIn('id="pvSampleStatusLine"', html)
        self.assertIn('id="pvSampleFee"', html)
        self.assertIn('id="pvSampleLeadTime"', html)
        self.assertIn('data-pdf-lbl="lbl_meta_sample_fee"', html)
        self.assertIn('data-pdf-lbl="lbl_meta_sample_lead_time"', html)
        self.assertIn('data-pdf-lbl="lbl_meta_authorized_payee"', html)
        self.assertIn('id="pvAuthorizedPayeeLine"', html)
        self.assertIn('data-pdf-lbl="foot_bank_account_prefix"', html)
        self.assertIn("打样费", html)
        self.assertIn("打样时间", html)

    def test_pdf_yellow_validity_bar_in_table_tfoot(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn('id="pvValidityYellowFoot"', html)
        self.assertNotIn('id="pvValidityYellowFoot" hidden', html)
        self.assertIn('data-pdf-lbl="foot_validity"', html)
        self.assertIn("以上报价20天内有效", html)
        yellow_pos = html.index('data-pdf-lbl="foot_validity"')
        sample_pos = html.index('id="pvSampleFeeLine"')
        self.assertLess(yellow_pos, sample_pos)
        self.assertIn("syncPdfValidityRemark", js)
        self.assertIn("yellowFoot.hidden = false", js)

    def test_pdf_remark_above_sample_fee(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="pvPdfRemarkLine"', html)
        self.assertIn('id="pvPdfRemark"', html)
        self.assertIn('data-pdf-lbl="lbl_meta_pdf_remark"', html)
        remark_pos = html.index('id="pvPdfRemarkLine"')
        fee_pos = html.index('id="pvSampleFeeLine"')
        yellow_pos = html.index('data-pdf-lbl="foot_validity"')
        self.assertLess(yellow_pos, remark_pos)
        self.assertLess(remark_pos, fee_pos)
        self.assertIn("syncPdfBottomRemark", js)
        self.assertIn("readPdfRemarkFromForm", js)
        self.assertIn("stripValidityRemarkFromPdfNote", js)
        self.assertNotIn("PDF_VALIDITY_REMARK_CN", js)
        self.assertIn("pvPdfRemarkLine", js)
        self.assertIn("#pvPdfRemarkLine", css)
        remark_block = html[remark_pos : remark_pos + 220]
        self.assertNotIn("以上报价20天内有效", remark_block)

    def test_pdf_note_column_header_dynamic(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="pvThNoteColumn"', html)
        self.assertIn("setPdfNoteColumnHeader", js)
        self.assertIn("shouldRenderPdfNoteColumn", js)
        self.assertIn("syncPdfNoteColumnLayout", js)
        self.assertIn("resolvePdfNoteColumnValue", js)
        self.assertIn('th.textContent = "含税价"', js)
        self.assertIn('th.innerHTML = "FOB价格<br />USD"', js)
        self.assertIn('lang === "en" && forFobUsdExport', js)
        self.assertIn('data-pdf-note-col="0"', css)
        self.assertIn(".qs-pdf-root[data-pdf-note-col=\"0\"] .qs-pdf-table .col-total", css)

    def test_sample_meta_text_value_css(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".qs-pdf-meta-text-value", css)
        block_start = css.index(".qs-pdf-meta-text-value")
        block = css[block_start : block_start + 220]
        self.assertIn("overflow-wrap: break-word", block)

    def test_payee_company_ui_present(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="qsPayeeCompany"', html)
        self.assertIn('id="qsPayeeToggle"', html)
        self.assertIn('id="qsPayeePreview"', html)
        self.assertIn('id="pvBank"', html)
        self.assertIn('id="pvBankAccount"', html)
        self.assertIn('id="pvBankAccountLine"', html)
        self.assertIn("qs-pdf-bank-account-line", html)
        self.assertIn('id="pvAlipay"', html)
        self.assertIn("收款公司", html)
        self.assertIn('role="combobox"', html)
        self.assertNotIn("根据各自团队收款信息为准", html)

    def test_payee_combobox_styles_present(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".qs-payee-combobox", css)
        self.assertIn(".qs-payee-candidate-meta", css)
        self.assertIn(".qs-payee-candidate-btn.is-active", css)

    def test_export_preflight_modal_present(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="qsExportPreflightModal"', html)
        self.assertIn('id="qsExportPreflightFill"', html)
        self.assertIn('id="qsExportPreflightProceed"', html)
        self.assertIn("导出前请确认以下信息", html)

    def test_quote_sheet_js_export_preflight_validation(self) -> None:
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn("validateBeforeExport", js)
        self.assertIn("ensureExportPreflight", js)
        self.assertIn("exportGuard.inflight", js)
        self.assertIn("showExportPreflightDialog", js)
        self.assertIn("请先选择收款公司", js)
        self.assertIn("请填写打样费", js)
        self.assertIn("请填写打样时间", js)
        self.assertIn("preflightSkipped", js)
        self.assertIn("fetchPayeeAccounts", js)
        self.assertNotIn('readSampleRequiredFromForm() === "no"', js)
        self.assertNotIn("根据各自团队收款信息为准", js)

    def test_pdf_footer_layout_spacing_in_css(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        root_start = css.index(".qs-pdf-root {")
        root_block = css[root_start : root_start + 1500]
        self.assertIn("--qs-pdf-footer-inset: 6px", root_block)
        self.assertIn("--qs-pdf-meta-right-left: 108mm", root_block)
        self.assertIn("--qs-pdf-meta-right-shift-x: 27mm", root_block)
        self.assertIn("--qs-pdf-signature-shift-y: calc(35pt + 10mm)", root_block)
        self.assertIn("--qs-pdf-signature-shift-y-cn-bump: 5mm", root_block)
        self.assertIn("--qs-pdf-signature-shift-y-en-bump: 10mm", root_block)
        self.assertIn("--qs-pdf-signature-shift-y-extra: 20mm", root_block)
        self.assertIn("--qs-pdf-stamp-shift-y-en: calc(", root_block)
        self.assertIn("--qs-pdf-cust-shift-y-en: calc(", root_block)
        self.assertIn("var(--qs-pdf-signature-shift-y-extra)", root_block)
        self.assertIn("--qs-pdf-en-sign-text-offset:", root_block)
        self.assertIn("--qs-pdf-en-sign-block-min-h: 30mm", root_block)

        sample_start = css.index(".qs-pdf-sample-meta")
        sample_block = css[sample_start : sample_start + 220]
        self.assertIn("padding: 2px var(--qs-pdf-footer-inset)", sample_block)
        self.assertIn("font-size: 10pt", sample_block)
        self.assertIn("line-height: 1.5", sample_block)

        pay_start = css.index(".qs-pdf-pay-wrap")
        pay_block = css[pay_start : pay_start + 280]
        self.assertIn("30%", pay_block)
        self.assertIn("46%", pay_block)
        self.assertIn("padding-left: 0", pay_block)

        stamp_start = css.index(".qs-pdf-stamp-side {")
        stamp_block = css[stamp_start : stamp_start + 360]
        self.assertIn("padding-left: var(--qs-pdf-footer-inset)", stamp_block)
        self.assertIn("align-self: end", stamp_block)
        self.assertIn("margin-top: var(--qs-pdf-stamp-shift-y-cn)", stamp_block)
        self.assertNotIn("transform: translateY(var(--qs-pdf-stamp-shift-y-cn))", stamp_block)

        pay_inner_start = css.index(".qs-pdf-pay-inner")
        pay_inner_block = css[pay_inner_start : pay_inner_start + 320]
        self.assertIn("position: absolute", pay_inner_block)
        self.assertIn("left: var(--qs-pdf-footer-inset)", pay_inner_block)
        self.assertIn("font-size: 10pt", pay_inner_block)
        self.assertIn("line-height: 1.5", pay_inner_block)

        bank_start = css.index(".qs-pdf-bank {")
        bank_block = css[bank_start : bank_start + 180]
        self.assertIn("font-size: 10pt", bank_block)
        self.assertIn("line-height: 1.55", bank_block)

        self.assertIn("#pvSampleStatusLine", css)
        status_start = css.index("#pvSampleStatusLine")
        status_block = css[status_start : status_start + 80]
        self.assertIn("display: none", status_block)

        footer_start = css.index(".qs-pdf-footer-co")
        footer_block = css[footer_start : footer_start + 200]
        self.assertIn("margin-top: 20px", footer_block)
        self.assertIn("overflow: visible", footer_block)

        sign_start = css.index(".qs-pdf-cust-sign-side {")
        sign_block = css[sign_start : sign_start + 260]
        self.assertIn("margin-top: var(--qs-pdf-cust-shift-y-cn)", sign_block)
        self.assertNotIn("transform: translateY(var(--qs-pdf-cust-shift-y-cn))", sign_block)

        en_sign_start = css.index('.qs-pdf-root[data-pdf-lang="en"] .qs-pdf-cust-sign-side')
        en_sign_block = css[en_sign_start : en_sign_start + 420]
        self.assertIn("align-self: start", en_sign_block)
        self.assertIn("margin-top: calc(var(--qs-pdf-cust-shift-y-en) + var(--qs-pdf-en-sign-text-offset))", en_sign_block)
        self.assertNotIn("transform: translateY(var(--qs-pdf-cust-shift-y-en))", en_sign_block)

        en_pay_start = css.index('.qs-pdf-root[data-pdf-lang="en"] .qs-pdf-pay-wrap')
        en_pay_block = css[en_pay_start : en_pay_start + 420]
        self.assertIn("--qs-pdf-en-sign-block-min-h)", en_pay_block)
        self.assertIn("--qs-pdf-en-sign-block-pad-bottom)", en_pay_block)

        en_footer_start = css.index('.qs-pdf-root[data-pdf-lang="en"] .qs-pdf-footer-co')
        en_footer_block = css[en_footer_start : en_footer_start + 320]
        self.assertIn("min-height: calc(2 * 1.55em + 0.45em)", en_footer_block)
        self.assertIn("padding-bottom: 0.45em", en_footer_block)

    def test_pdf_export_onclone_keeps_meta_right_shift(self) -> None:
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn('const PDF_META_RIGHT_SHIFT_X = "27mm"', js)
        self.assertIn("translateX(${PDF_META_RIGHT_SHIFT_X})", js)
        self.assertIn('.qs-pdf-cust-sign-side").forEach', js)
        self.assertIn("--qs-pdf-cn-sign-block-pad-bottom", js)
        self.assertIn('footerCo.style.setProperty("min-height"', js)
        self.assertNotIn("PDF_HEADER_RIGHT_ANCHOR", js)
        self.assertNotIn('cell.style.setProperty("padding-left", "45pt", "important")', js)
        self.assertNotIn('node.style.setProperty("overflow", "hidden", "important")', js)

    def test_pdf_name_column_wraps_in_css(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        block_start = css.index(".qs-pdf-table tbody td.col-name")
        block = css[block_start : block_start + 320]
        self.assertIn("white-space: normal", block)
        self.assertIn("overflow-wrap: anywhere", block)
        self.assertIn("max-width: 0", block)
        self.assertIn('textCell("col-name", true', js)
        self.assertIn("td.col-name", js)

    def test_pdf_bank_account_split_in_quote_sheet_js(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn("buildBankNamePdfText", js)
        self.assertIn("buildBankAccountPdfText", js)
        self.assertIn('setText("pvBank", bankNameText)', js)
        self.assertIn('setText("pvBankAccount", bankAccountText)', js)
        self.assertIn('el("pvBankAccountLine")', js)
        self.assertIn('QUOTE_ISSUER_COMPANY_NAME = "深圳市栢博旅游用品有限公司"', js)
        self.assertIn('QUOTE_PDF_HEADER_COMPANY_NAME_EN = "Shenzhen Peboz Products Limited"', js)
        self.assertIn("syncQuoteIssuerCompanyNameForPdf", js)
        self.assertIn('setText("pvCoTitle", resolvePdfHeaderCompanyName(lang))', js)
        self.assertIn('setText("pvFooterCo", resolveFooterCompanyNameForPdf(lang))', js)
        self.assertIn("resolveAuthorizedPayeeCompanyForPdf", js)
        self.assertIn("syncAuthorizedPayeePdfPreview", js)
        self.assertNotIn("metaEn?.co_name ?? coTitle", js)
        self.assertNotIn('setText("pvCoTitle", title)', js)
        self.assertNotIn("buildBankPdfText", js)
        self.assertIn('data-pdf-lbl="foot_bank_account_prefix"', html)

    def test_sample_pdf_preview_hides_status_line(self) -> None:
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn("statusLine.hidden = true", js)
        self.assertNotIn('statusLine.hidden = false', js)
        self.assertNotIn('qsSampleRequired', js)

    def test_desc_column_truncation_in_css(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".qs-pdf-table tbody td.col-desc", css)
        block_start = css.index(".qs-pdf-table tbody td.col-desc")
        block = css[block_start : block_start + 420]
        self.assertIn("overflow: hidden", block)
        self.assertIn("max-height: 3.75em", block)
        self.assertNotIn("-webkit-line-clamp", block)
        self.assertIn("tbody tr:last-child > td", css)

    def test_pdf_size_column_allows_wrap_without_clip(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn('<table class="qs-pdf-table"', html)
        table_start = html.index('<table class="qs-pdf-table"')
        table_head = html[table_start : table_start + 600]
        self.assertIn("<colgroup>", table_head)
        self.assertIn('class="col-size"', table_head)
        size_block_start = css.index(".qs-pdf-table tbody td.col-size,")
        size_block = css[size_block_start : size_block_start + 320]
        self.assertIn("overflow: visible", size_block)
        self.assertIn("white-space: normal", size_block)
        self.assertIn("overflow-wrap: break-word", size_block)
        self.assertIn(".qs-pdf-table col.col-size", css)
        self.assertIn("width: 14%", css[css.index(".qs-pdf-table .col-size") : css.index(".qs-pdf-table .col-size") + 40])
        self.assertIn("td.col-size, .qs-pdf-table td.col-pack", js)
        self.assertIn('col.style.setProperty("width", "14%"', js)

    def test_pdf_desc_sanitizer_strips_material_prefix_and_width(self) -> None:
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn("sanitizeCustomerDescForPdf", js)
        self.assertIn("PDF_DESC_MATERIAL_PREFIX_RE", js)
        self.assertIn("PDF_DESC_WIDTH_TOKEN_RE", js)
        self.assertIn("resolvePdfDescValue", js)

    def test_pdf_desc_dedupes_duplicate_materials(self) -> None:
        js = (ROOT / "static" / "quote_sheet.js").read_text(encoding="utf-8")
        self.assertIn("dedupePdfDescSegments", js)
        self.assertIn("PDF_DESC_SEGMENT_SPLIT_RE", js)
        self.assertIn("normalizePdfDescSegmentKey", js)

        def _strip_material_prefix_and_width(text: str) -> str:
            import re

            p = str(text or "").strip()
            if not p:
                return ""
            p = re.sub(
                r"^(?:主料|里布|面料|外料|辅料|main\s*material|lining|fabric)[：:\s]+",
                "",
                p,
                flags=re.I,
            )
            p = re.sub(r"宽幅[：:]?\s*", "", p, flags=re.I)
            p = re.sub(
                r"\d+(?:\.\d+)?\s*(?:cm|厘米|mm|毫米|''|\"|″|inch|in)\b",
                "",
                p,
                flags=re.I,
            )
            return re.sub(r"\s{2,}", " ", p).strip()

        def _dedupe_pdf_desc(raw: str) -> str:
            import re

            source = str(raw or "").strip()
            if not source:
                return ""
            seen: set[str] = set()
            kept: list[str] = []
            for part in re.split(r"[，,、/\r\n]+", source):
                cleaned = re.sub(r"\s+", " ", _strip_material_prefix_and_width(part)).strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                kept.append(cleaned)
            return "、".join(kept)

        sample = "主料：600D牛津布、210D涤纶、600D牛津布 152cm"
        self.assertEqual(_dedupe_pdf_desc(sample), "600D牛津布、210D涤纶")
        self.assertEqual(
            _dedupe_pdf_desc("600D牛津布, 210D涤纶, 600D牛津布"),
            "600D牛津布、210D涤纶",
        )
        self.assertEqual(_dedupe_pdf_desc("600D牛津布 / 210D涤纶 / 600D牛津布"), "600D牛津布、210D涤纶")
        self.assertEqual(_dedupe_pdf_desc(""), "")
        self.assertNotIn("主料：", _dedupe_pdf_desc(sample))
        self.assertNotIn("152cm", _dedupe_pdf_desc(sample))


if __name__ == "__main__":
    unittest.main()
