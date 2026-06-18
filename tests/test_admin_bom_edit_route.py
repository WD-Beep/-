"""后台 BOM 编辑：新增/删除物料 + POST /admin-api/quotes/{id}/bom-edit。"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from quote_upload_storage import (
    ADMIN_UPDATE_STATUS_PENDING,
    ADMIN_UPDATE_STATUS_VIEWED,
    get_saved_quote_admin_bundle,
    list_my_quotes_for_sales_user,
    mark_sales_admin_update_viewed,
    save_quote_calculation,
)
from server import QuoteHandler
from test_db_isolation import cleanup_isolated_quote_db, mount_isolated_quote_db, restore_quote_db

ROOT = Path(__file__).resolve().parents[1]


def _attach_site(httpd: HTTPServer, site: str) -> None:
    setattr(httpd, "_quote_site", site)


def _admin_headers() -> dict[str, str]:
    return {"X-User-Role": "admin", "Content-Type": "application/json; charset=utf-8"}


def _quote_with_one_item(calc_id: str) -> dict:
    return {
        "quote_id": calc_id,
        "product_name": "BOM编辑测试包",
        "material_total": 10.0,
        "processing_fee": 5.0,
        "mold_fee": 0.0,
        "system_overhead": 2.0,
        "tiers": [
            {
                "quantity": 500,
                "cost_before_margin": 17.0,
                "processing_fee": 5.0,
            }
        ],
        "cost_bridge": {"system_overhead_per_pc": 2.0, "processing_fee_per_pc": 5.0},
        "detail_rows": [
            {
                "name": "主料A",
                "spec": "规格A",
                "usage": "1",
                "unit_price": "10元/㎡",
                "amount": 10.0,
            }
        ],
        "items": [
            {
                "name": "主料A",
                "spec": "规格A",
                "usage": "1",
                "unit_price": "10元/㎡",
            }
        ],
    }


class AdminBomEditStaticWiringTest(unittest.TestCase):
    def test_admin_html_has_add_button(self) -> None:
        html = (ROOT / "static" / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="btnBomAdd"', html)
        self.assertIn("新增物料", html)

    def test_admin_js_has_add_delete_handlers(self) -> None:
        js = (ROOT / "static" / "admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("function addBomEditRow", js)
        self.assertIn("function deleteBomEditRowAt", js)
        self.assertIn("window.confirm", js)
        self.assertIn("[data-bom-row-delete]", js)
        self.assertIn("[data-bom-add-row]", js)
        self.assertIn('btnBomAdd.addEventListener("click"', js)

    def test_admin_js_renders_requirement_view_above_material_rows(self) -> None:
        js = (ROOT / "static" / "admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("function renderBomRequirementView", js)
        self.assertIn("quote?.bom_requirement_view", js)
        self.assertLess(js.index("renderBomRequirementView"), js.index("renderBomEditMaterialTable"))

    def test_sales_app_renders_requirement_view_above_previews(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function buildBomRequirementViewHtml", js)
        self.assertIn("quote?.bom_requirement_view", js)
        self.assertIn("quote?.bom_requirement_view", js)
        self.assertLess(js.index("buildBomRequirementViewHtml(quote)"), js.index("quote-detail-section"))
        self.assertLess(js.index("buildBomRequirementViewHtml(data, {"), js.index("structure-confirm-workspace"))

    def test_sales_app_uses_requirement_view_as_demand_confirmation_editor(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function isDemandRequirementConfirmation", js)
        self.assertIn("function saveRequirementViewEdits", js)
        self.assertIn("function cancelRequirementViewEdits", js)
        self.assertIn("data-requirement-view-edit", js)
        self.assertIn("data-requirement-view-save", js)
        self.assertIn("data-requirement-view-cancel", js)
        self.assertIn("manual_requirement_fields", js)
        self.assertIn("manual_materials_detail_rows", js)
        self.assertIn("!isDemandMode", js)
        self.assertLess(js.index("buildBomRequirementViewHtml(data, {"), js.index("!isDemandMode"))

    def test_sales_app_only_expands_piece_details_when_pieces_exist(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        start = js.index("function renderMaterialDetailAreaRowHtml")
        end = js.index("function renderMaterialDetailTableBody")
        block = js[start:end]
        self.assertIn("hasPieceRows", block)
        self.assertIn("${hasPieceRows", block)
        self.assertNotIn('return `<p class="muted mat-area-empty">暂无裁片明细', block)

    def test_sales_app_no_global_material_overview_footer(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("function renderMaterialDetailOverviewFooter", js)
        self.assertNotIn("mat-detail-overview-row", js)
        self.assertNotIn("材料面积汇总", js)
        self.assertNotIn("mat-sum-block", js)

    def test_sales_app_summary_lookup_prefers_row_index(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("if (lookup.byIndex.has(index)) return lookup.byIndex.get(index)", js)
        self.assertIn("byKeyQueues", js)
        self.assertIn("consumedKeys", js)

    def test_sales_app_display_summary_skips_main_table_fields(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        start = js.index("function renderMaterialDisplaySummaryHtml")
        end = js.index("function renderMaterialMeasureBriefHtml")
        block = js[start:end]
        self.assertNotIn("mat-area-summary-title", block)
        self.assertNotIn("ds.title", block)
        self.assertNotIn("核算尺寸", block)
        self.assertNotIn("结构尺寸", block)

    def test_sales_static_bundle_version_bumped_for_requirement_view(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/styles.css?v=bom-requirement-af-20260617", html)
        self.assertIn("/static/app.js?v=bom-requirement-af-20260617", html)


class AdminBomEditRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved = mount_isolated_quote_db()
        self.series_uid = "bom-edit-series"
        self.calc_id = "bom-edit-calc"
        save_quote_calculation(
            quote_uid=self.series_uid,
            calc_quote_id=self.calc_id,
            sheet_original_display_name="bom-test.xlsx",
            uploaded_sheet=None,
            quote_result=_quote_with_one_item(self.calc_id),
        )
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "admin")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()
        restore_quote_db(self._saved)
        cleanup_isolated_quote_db(self._root)

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request(
            "POST",
            path,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=_admin_headers(),
        )
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _bom_payload(self, items: list[dict]) -> dict:
        return {
            "product": {"product_name": "BOM编辑测试包", "quantities_text": "500个", "margin_text": "35%"},
            "items": items,
        }

    def test_bom_edit_add_row_persists(self) -> None:
        before = get_saved_quote_admin_bundle(self.series_uid)
        self.assertEqual(len(before.get("items") or []), 1)

        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [
                    {"name": "主料A", "spec": "规格A", "usage": "1", "unit_price": "10元/㎡"},
                    {"name": "新增主料B", "spec": "-", "usage": "2", "unit_price": "5元/个"},
                ]
            ),
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"), msg=body)

        after = get_saved_quote_admin_bundle(self.series_uid)
        names = [str(it.get("name") or "") for it in (after.get("items") or [])]
        self.assertIn("新增主料B", names)
        self.assertEqual(len(names), 2)

    def test_bom_edit_delete_row_persists(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [
                    {"name": "主料A", "spec": "规格A", "usage": "1", "unit_price": "10元/㎡"},
                    {"name": "待删行", "spec": "-", "usage": "1", "unit_price": "3元/个"},
                ]
            ),
        )
        self.assertEqual(code, 200, msg=body)

        code2, body2 = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [{"name": "主料A", "spec": "规格A", "usage": "1", "unit_price": "10元/㎡"}]
            ),
        )
        self.assertEqual(code2, 200, msg=body2)

        after = get_saved_quote_admin_bundle(self.series_uid)
        names = [str(it.get("name") or "") for it in (after.get("items") or [])]
        self.assertEqual(names, ["主料A"])

    def test_bom_edit_rejects_empty_material_name(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload([{"name": "", "usage": "1", "unit_price": "6"}]),
        )
        self.assertEqual(code, 400, msg=body)
        self.assertEqual(body.get("error"), "validation_failed")
        self.assertIn("items.0.name", body.get("field_errors") or {})

    def test_bom_edit_rejects_invalid_usage_via_api(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload([{"name": "主料A", "usage": "1abc", "unit_price": "10元/㎡"}]),
        )
        self.assertEqual(code, 400, msg=body)
        self.assertEqual(body.get("error"), "validation_failed")
        self.assertIn("items.0.usage", body.get("field_errors") or {})

    def test_bom_edit_rejects_invalid_unit_price_via_api(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload([{"name": "主料A", "usage": "1", "unit_price": "2..3"}]),
        )
        self.assertEqual(code, 400, msg=body)
        self.assertIn("items.0.unit_price", body.get("field_errors") or {})

    def test_bom_edit_accepts_number_with_unit_via_api(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [{"name": "主料A", "usage": "2.5码", "unit_price": "5元/个"}],
            ),
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"), msg=body)


class AdminBomEditAdminUpdateFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root, self._saved = mount_isolated_quote_db()
        self.series_uid = "bom-update-series"
        self.calc_id = "bom-update-calc"
        self.sales_uid = "sales-bom-update"
        save_quote_calculation(
            quote_uid=self.series_uid,
            calc_quote_id=self.calc_id,
            sheet_original_display_name="bom-update.xlsx",
            uploaded_sheet=None,
            quote_result=_quote_with_one_item(self.calc_id),
            sales_user_id=self.sales_uid,
        )
        self.httpd = HTTPServer(("127.0.0.1", 0), QuoteHandler)
        _attach_site(self.httpd, "admin")
        self.port = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.th.join(timeout=2)
        self.httpd.server_close()
        restore_quote_db(self._saved)
        cleanup_isolated_quote_db(self._root)

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request(
            "POST",
            path,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=_admin_headers(),
        )
        resp = conn.getresponse()
        buf = resp.read()
        conn.close()
        try:
            body = json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        return resp.status, body if isinstance(body, dict) else {}

    def _bom_payload(self, items: list[dict]) -> dict:
        return {
            "product": {"product_name": "BOM编辑测试包", "quantities_text": "500个", "margin_text": "35%"},
            "items": items,
        }

    def test_bom_edit_marks_pending_view_and_sales_list(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [
                    {"name": "主料A", "spec": "规格A", "usage": "1", "unit_price": "10元/㎡"},
                    {"name": "新增主料B", "spec": "-", "usage": "2", "unit_price": "5元/个"},
                ]
            ),
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"), msg=body)

        bundle = get_saved_quote_admin_bundle(self.series_uid)
        meta = bundle.get("meta") or {}
        self.assertEqual(meta.get("admin_update_status"), ADMIN_UPDATE_STATUS_PENDING)
        self.assertTrue(meta.get("admin_update_at"))
        self.assertFalse(meta.get("admin_update_viewed_at"))
        self.assertTrue(meta.get("admin_feedback_at"))
        self.assertEqual(meta.get("admin_feedback_by"), "admin")
        self.assertEqual(int(meta.get("latest_version_no") or 0), 2)

        items = list_my_quotes_for_sales_user(self.sales_uid)
        row = next((x for x in items if x.get("quote_series_uid") == self.series_uid), None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row.get("has_admin_update"))

    def test_bom_edit_viewed_then_reedit_repends(self) -> None:
        code1, body1 = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [{"name": "主料A", "spec": "规格A", "usage": "1.2", "unit_price": "10元/㎡"}]
            ),
        )
        self.assertEqual(code1, 200, msg=body1)

        viewed = mark_sales_admin_update_viewed(self.series_uid, self.sales_uid)
        self.assertIsNotNone(viewed)
        assert viewed is not None
        self.assertEqual(
            (viewed.get("admin_feedback") or {}).get("admin_update_status"),
            ADMIN_UPDATE_STATUS_VIEWED,
        )
        items_viewed = list_my_quotes_for_sales_user(self.sales_uid)
        row_viewed = next((x for x in items_viewed if x.get("quote_series_uid") == self.series_uid), None)
        assert row_viewed is not None
        self.assertFalse(row_viewed.get("has_admin_update"))

        code2, body2 = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [{"name": "主料A", "spec": "规格A", "usage": "1.5", "unit_price": "10元/㎡"}]
            ),
        )
        self.assertEqual(code2, 200, msg=body2)

        bundle = get_saved_quote_admin_bundle(self.series_uid)
        meta = bundle.get("meta") or {}
        self.assertEqual(meta.get("admin_update_status"), ADMIN_UPDATE_STATUS_PENDING)
        self.assertFalse(meta.get("admin_update_viewed_at"))

        items_pending = list_my_quotes_for_sales_user(self.sales_uid)
        row_pending = next((x for x in items_pending if x.get("quote_series_uid") == self.series_uid), None)
        assert row_pending is not None
        self.assertTrue(row_pending.get("has_admin_update"))

    def test_bom_edit_count_based_empty_usage_saves_and_recalcs(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [
                    {"name": "DCH外料", "spec": "-", "usage": "1.12码", "unit_price": "10元/㎡"},
                    {"name": "普通拉头", "spec": "-", "usage": "-", "unit": "元/个", "unit_price": "0.3"},
                ]
            ),
        )
        self.assertEqual(code, 200, msg=body)
        self.assertTrue(body.get("ok"), msg=body)
        quote = body.get("quote") if isinstance(body.get("quote"), dict) else {}
        rows = quote.get("detail_rows") if isinstance(quote.get("detail_rows"), list) else []
        zipper = next((r for r in rows if str(r.get("name") or "") == "普通拉头"), None)
        self.assertIsNotNone(zipper, msg=rows)
        assert zipper is not None
        usage_text = str(zipper.get("usage") or "")
        self.assertTrue(usage_text.startswith("1"), msg=usage_text)
        amt = zipper.get("amount")
        if amt is not None:
            self.assertFalse(isinstance(amt, float) and amt != amt)

    def test_admin_bundle_contains_requirement_view_with_missing_values_as_none_text(self) -> None:
        bundle = get_saved_quote_admin_bundle(self.series_uid)
        self.assertIsNotNone(bundle)
        quote = bundle.get("quote") or {}
        view = quote.get("bom_requirement_view")
        self.assertIsInstance(view, dict)
        self.assertEqual(view.get("empty_text"), "无")
        sections = view.get("sections")
        self.assertIsInstance(sections, list)
        self.assertEqual([s.get("key") for s in sections], ["A", "B", "C", "D", "E", "F"])
        product = next(s for s in sections if s.get("key") == "B")
        values = {f.get("key"): f.get("value") for f in product.get("fields", [])}
        self.assertEqual(values.get("product_name_model"), "BOM编辑测试包")
        self.assertEqual(values.get("length_cm"), "无")

    def test_bom_edit_non_count_empty_usage_rejected(self) -> None:
        code, body = self._post_json(
            f"/admin-api/quotes/{self.series_uid}/bom-edit",
            self._bom_payload(
                [{"name": "DCH外料", "spec": "-", "usage": "-", "unit_price": "10元/码"}]
            ),
        )
        self.assertNotEqual(code, 200)
        self.assertNotEqual(body.get("ok"), True)


if __name__ == "__main__":
    unittest.main()
