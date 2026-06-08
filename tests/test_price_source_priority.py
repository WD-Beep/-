"""单价来源优先级 / 冲突 / 待审隔离 — 回归测试。"""
from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover
    Workbook = None

from kb_data_quality import KB_ACTION_DROP, KB_ACTION_REVIEW, judge_kb_insert_candidate
from price_admin_store import (
    AUTO_CONFLICT_MARKER,
    AUTO_PENDING_MARKER,
    enqueue_price_learn_candidate,
    list_price_exceptions,
    lookup_confirmed_price_override,
    sync_quote_detail_rows_to_price_kb,
    upsert_confirmed_price_override,
)
from price_kb import apply_kb_lookup_fields, apply_material_price_lookup
from price_learn_candidate import is_quote_blocking_learn_candidate
from price_source_resolver import (
    PRICE_SOURCE_KB,
    PRICE_SOURCE_OVERRIDE,
    PRICE_SOURCE_SHEET,
    merge_kb_lookup_into_row,
)
from quote_engine import parse_items


class _FakeEntry:
    def __init__(self, name: str, spec: str, price: str) -> None:
        self.raw_name = name
        self.raw_spec = spec
        self.raw_price = price
        self.auto_learned = False


class _FakeKbHit:
    def __init__(self, entry: _FakeEntry, score: float = 1.0) -> None:
        self.entry = entry
        self.score = score


@unittest.skipIf(Workbook is None, "openpyxl is required")
class PriceSourcePriorityTest(unittest.TestCase):
    def _make_root(self) -> Path:
        root = Path(__file__).resolve().parents[1] / "data" / f"_tmp_price_src_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _make_kb(self, root: Path, rows: list[tuple[str, str, str]]) -> Path:
        kb_path = root / "price_kb.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "材料询价"
        ws.append(["材料名称", "规格大小", "单价", "标记", "状态", "备注", "更新时间", "更新人"])
        for name, spec, price in rows:
            ws.append([name, spec, price, "", "active", "", "2026-06-08 10:00:00", "seed"])
        wb.save(kb_path)
        wb.close()
        return kb_path

    def test_business_sheet_price_blocks_kb_and_override_overwrite(self) -> None:
        """业务表价存在时，KB/override 不得覆盖；仅记录冲突候选。"""
        row = {
            "name": "五金标准扣具",
            "spec": "常规",
            "unit_price": "0.35元/个",
            "price_source": PRICE_SOURCE_SHEET,
            "usage": "1个",
            "amount": 0.35,
        }
        fields = apply_kb_lookup_fields(
            material_name="五金标准扣具",
            entry=_FakeEntry("五金标准扣具", "常规", "0.3元/个"),
            hit_score=1.0,
            existing_row=row,
        )
        self.assertEqual(fields["unit_price"], "0.35元/个")
        self.assertEqual(fields["price_source"], PRICE_SOURCE_SHEET)
        self.assertTrue(fields.get("price_conflict_required"))
        self.assertFalse(fields.get("kb_hit"))
        self.assertFalse(fields.get("override_hit"))
        items = parse_items([{**row, **fields}])
        self.assertEqual(items[0].unit_price, "0.35元/个")

    def test_override_used_before_kb_without_business_price(self) -> None:
        """无业务价时，已确认 override 优先于正式 KB。"""
        root = self._make_root()
        try:
            override_path = root / "price_overrides.jsonl"
            upsert_confirmed_price_override(
                material_name="五金标准扣具",
                spec="常规",
                price="0.35元/个",
                operator="admin",
                override_path=override_path,
            )
            row = {"name": "五金标准扣具", "spec": "常规", "unit_price": "-"}
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                fields = apply_material_price_lookup(
                    material_name="五金标准扣具",
                    spec="常规",
                    existing_row=row,
                    kb_hit=_FakeKbHit(_FakeEntry("五金标准扣具", "常规", "0.3元/个")),
                )
            self.assertEqual(fields["unit_price"], "0.35元/个")
            self.assertEqual(fields["price_source"], PRICE_SOURCE_OVERRIDE)
            self.assertTrue(fields.get("override_hit"))
            self.assertFalse(fields.get("kb_hit"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_kb_used_when_no_business_price_and_no_override(self) -> None:
        row = {"name": "普通拉头", "spec": "5#", "unit_price": "-"}
        fields = apply_kb_lookup_fields(
            material_name="普通拉头",
            entry=_FakeEntry("普通拉头", "5#", "0.3元/个"),
            hit_score=1.0,
            existing_row=row,
        )
        self.assertEqual(fields["unit_price"], "0.3元/个")
        self.assertEqual(fields["price_source"], PRICE_SOURCE_KB)
        self.assertTrue(fields.get("kb_hit"))

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_price_conflict_goes_pending_not_overwrite_quote(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [("五金标准扣具", "常规", "0.3元/个")])
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "c4bbcd50-d0d4-46b9-9cf9-2fd94c84d76f",
                        "product_name": "斜挎包",
                        "detail_rows": [
                            {
                                "name": "五金标准扣具",
                                "spec": "常规",
                                "unit_price": "0.35元/个",
                                "price_source": "sheet",
                                "price_conflict_required": True,
                                "kb_matched_name": "五金标准扣具",
                                "kb_reference_price": "0.3元/个",
                                "usage": "1个",
                                "amount": 0.35,
                            }
                        ],
                    },
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    exception_path=root / "price_exceptions.jsonl",
                )
            self.assertEqual(summary["conflicts"], 1)
            pending, total = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(total, 1)
            self.assertEqual(pending[0]["marker"], AUTO_CONFLICT_MARKER)
            self.assertTrue(is_quote_blocking_learn_candidate(pending[0]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_pending_open_candidate_never_participates_in_quote_lookup(self) -> None:
        """pending/open 候选只在后台队列，查价回退正式 KB。"""
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [("五金标准扣具", "常规", "0.3元/个")])
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                pending_row = enqueue_price_learn_candidate(
                    material_name="五金标准扣具",
                    spec="常规",
                    new_price="0.35元/个",
                    source_type="price_conflict",
                    marker=AUTO_PENDING_MARKER,
                    exception_path=root / "price_exceptions.jsonl",
                )
                self.assertTrue(is_quote_blocking_learn_candidate(pending_row))
                self.assertIsNone(
                    lookup_confirmed_price_override(
                        "五金标准扣具",
                        "常规",
                        override_path=root / "price_overrides.jsonl",
                    )
                )
                fields = apply_material_price_lookup(
                    material_name="五金标准扣具",
                    spec="常规",
                    existing_row={"name": "五金标准扣具", "spec": "常规", "unit_price": "-"},
                    kb_hit=_FakeKbHit(_FakeEntry("五金标准扣具", "常规", "0.3元/个")),
                )
            self.assertEqual(fields["unit_price"], "0.3元/个")
            self.assertEqual(fields["price_source"], PRICE_SOURCE_KB)
            self.assertFalse(fields.get("override_hit"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_garbage_names_cannot_enter_override_layer(self) -> None:
        """表头/部位/合计等垃圾名不得进入覆盖层。"""
        root = self._make_root()
        try:
            override_path = root / "price_overrides.jsonl"
            for garbage_name in ("前片", "合计", "侧片"):
                verdict = judge_kb_insert_candidate(garbage_name, "-", "2元/个")
                self.assertEqual(verdict.action, KB_ACTION_DROP, garbage_name)
                with self.assertRaises(ValueError):
                    upsert_confirmed_price_override(
                        material_name=garbage_name,
                        spec="-",
                        price="2元/个",
                        override_path=override_path,
                    )
                self.assertIsNone(
                    lookup_confirmed_price_override(garbage_name, "-", override_path=override_path)
                )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_abnormal_kb_slider_price_rejected_for_quote(self) -> None:
        row = {"name": "金色拉头", "spec": "普通拉头", "unit_price": "-"}
        fields = apply_kb_lookup_fields(
            material_name="金色拉头",
            entry=_FakeEntry("金色拉头", "普通拉头", "60元/个"),
            hit_score=0.9,
            existing_row=row,
        )
        self.assertEqual(fields["unit_price"], "-")
        self.assertFalse(fields.get("kb_hit"))
        self.assertTrue(fields.get("kb_price_rejected"))

    def test_abnormal_slider_pending_cannot_become_override(self) -> None:
        root = self._make_root()
        try:
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                enqueue_price_learn_candidate(
                    material_name="金色拉头",
                    spec="普通拉头",
                    new_price="60元/个",
                    source_type="ai_estimate",
                    marker=AUTO_PENDING_MARKER,
                    exception_path=root / "price_exceptions.jsonl",
                )
                with self.assertRaises(ValueError):
                    upsert_confirmed_price_override(
                        material_name="金色拉头",
                        spec="普通拉头",
                        price="60元/个",
                        override_path=root / "price_overrides.jsonl",
                    )
                fields = apply_material_price_lookup(
                    material_name="普通拉头",
                    spec="5#",
                    existing_row={"name": "普通拉头", "spec": "5#", "unit_price": "-"},
                    kb_hit=_FakeKbHit(_FakeEntry("普通拉头", "5#", "0.3元/个")),
                )
            self.assertEqual(fields["unit_price"], "0.3元/个")
            self.assertEqual(fields["price_source"], PRICE_SOURCE_KB)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_special_fee_cannot_override_normal_slider(self) -> None:
        verdict = judge_kb_insert_candidate("拉头烤漆费", "-", "60元")
        self.assertEqual(verdict.action, KB_ACTION_REVIEW)
        with self.assertRaises(ValueError):
            upsert_confirmed_price_override(material_name="拉头烤漆费", spec="-", price="60元")
        fields = apply_material_price_lookup(
            material_name="普通拉头",
            spec="5#",
            existing_row={"name": "普通拉头", "spec": "5#", "unit_price": "-"},
            kb_hit=_FakeKbHit(_FakeEntry("普通拉头", "5#", "0.3元/个")),
        )
        self.assertEqual(fields["price_source"], PRICE_SOURCE_KB)

    def test_business_sheet_price_not_sanitized_as_kb_outlier(self) -> None:
        """业务表价即使看似异常，也不被 KB 异常价规则清洗。"""
        row = {
            "name": "黑色拉头*1",
            "spec": "普通拉头",
            "unit_price": "60元/个",
            "price_source": PRICE_SOURCE_SHEET,
            "usage": "1个",
        }
        merged = merge_kb_lookup_into_row(
            row,
            material_name="黑色拉头*1",
            kb_fields={"kb_matched_name": "金色拉头", "kb_matched_spec": "普通拉头"},
            kb_display_price="60元/个",
            kb_rejected=True,
            kb_reject_reason="拉链/拉头单价明显异常，疑似总价误填为单价，待人工确认",
        )
        self.assertEqual(merged["unit_price"], "60元/个")
        self.assertEqual(merged["price_source"], PRICE_SOURCE_SHEET)

    def test_ai_estimate_cannot_auto_enter_override(self) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [])
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "c8a1b2d3-e4f5-6789-abcd-ef0123456789",
                        "product_name": "斜挎包",
                        "detail_rows": [
                            {
                                "name": "NEW_WEBBING",
                                "spec": "25MM",
                                "unit_price": "0.55元/米",
                                "unit_price_ai": True,
                                "price_source": "ai_estimate",
                                "source": "ai",
                                "usage": "1米",
                            }
                        ],
                    },
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    exception_path=root / "price_exceptions.jsonl",
                )
            self.assertGreaterEqual(summary["pending"], 1)
            self.assertIsNone(
                lookup_confirmed_price_override("NEW_WEBBING", "25MM", override_path=root / "price_overrides.jsonl")
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @patch("price_admin_store.knowledge_reload_hook")
    @patch("price_admin_store.note_kb_disk_write_success")
    def test_sheet_price_sync_goes_pending_not_auto_sync(self, _n: object, _r: object) -> None:
        root = self._make_root()
        try:
            kb_path = self._make_kb(root, [])
            with patch.dict(os.environ, {"PRICE_REVIEW_DATA_DIR": str(root)}):
                summary = sync_quote_detail_rows_to_price_kb(
                    {
                        "quote_ready": True,
                        "quote_id": "ad3b9a1b-19d1-43f9-961b-647b0cea6b96",
                        "product_name": "牛仔单肩包",
                        "detail_rows": [
                            {
                                "name": "新织带",
                                "spec": "20MM",
                                "unit_price": "0.55元/米",
                                "price_source": "sheet",
                                "usage": "1米",
                                "amount": 0.55,
                            }
                        ],
                    },
                    kb_path=kb_path,
                    history_path=root / "history.jsonl",
                    exception_path=root / "price_exceptions.jsonl",
                )
            self.assertEqual(summary["pending"], 1)
            pending, _ = list_price_exceptions(
                page=1, page_size=20, exception_path=root / "price_exceptions.jsonl"
            )
            self.assertEqual(pending[0]["marker"], AUTO_PENDING_MARKER)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
