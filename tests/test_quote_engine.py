import unittest

from demand_parser import wants_fob_from_price_type
from quote_engine import calculate_quote


class FobTypeDetectionTest(unittest.TestCase):
    def test_wants_fob_from_price_type(self) -> None:
        self.assertFalse(wants_fob_from_price_type(""))
        self.assertFalse(wants_fob_from_price_type("   "))
        self.assertFalse(wants_fob_from_price_type("出厂"))
        self.assertTrue(wants_fob_from_price_type("FOB"))
        self.assertTrue(wants_fob_from_price_type("fob"))
        self.assertTrue(wants_fob_from_price_type("出厂/FOB"))


class QuoteEngineTest(unittest.TestCase):
    def test_per_tier_gross_margins_change_exw(self) -> None:
        result = calculate_quote(
            {
                "gross_margin_by_quantity": {"300": 0.35, "500": 0.30, "1000": 0.25},
            }
        )
        self.assertFalse(result["settings"]["gross_margin_uniform"])
        tiers = result["tiers"]
        self.assertEqual(tiers[0]["margin_rate_text"], "35%")
        self.assertEqual(tiers[1]["margin_rate_text"], "30%")
        self.assertEqual(tiers[2]["margin_rate_text"], "25%")
        self.assertNotEqual(tiers[0]["exw_price"], tiers[1]["exw_price"])

    def test_auto_learned_kb_marker_survives_detail_rows(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "auto-learned-row",
                        "spec": "-",
                        "usage": "1PCS",
                        "unit_price": "2.50/PCS",
                        "amount": 2.5,
                        "source": "kb",
                        "kb_hit": True,
                        "kb_auto_learned": True,
                    },
                ],
            }
        )

        self.assertTrue(result["detail_rows"][0]["kb_auto_learned"])

    def test_reference_prices_margin_per_quantity(self) -> None:
        result = calculate_quote(
            {
                "reference_prices": [
                    {"quantity": 300, "margin": 0.35, "cost": 100.0, "quote": 200.0},
                    {"quantity": 500, "margin": 0.30, "cost": 100.0, "quote": 180.0},
                ],
            }
        )
        self.assertFalse(result["settings"]["gross_margin_uniform"])
        self.assertEqual(result["tiers"][0]["margin_rate_text"], "35%")
        self.assertEqual(result["tiers"][1]["margin_rate_text"], "30%")
        self.assertEqual(result["tiers"][2]["margin_rate_text"], "35%")

    def test_sales_sheet_checkpoint_matches_written_cost_when_tier_aligns(self) -> None:
        result = calculate_quote(
            {
                "quantities": [500, 1000],
                "mold_fee": 1000.0,
                "processing_fee": 15.0,
                "system_overhead": 4.0,
                "reference_prices": [
                    {
                        "quantity": 500,
                        "cost": 361.78,
                        "margin": 0.35,
                        "quote": 557.0,
                        "source_text": "500个手写",
                    },
                ],
                "items": [
                    {
                        "name": "占位主料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "340.78元",
                        "amount": 340.78,
                    },
                ],
            },
        )
        cps = result.get("sales_sheet_checkpoints") or []
        self.assertEqual(len(cps), 1)
        self.assertEqual(cps[0]["quantity"], 500)
        self.assertLess(abs(float(cps[0]["gap_pc"])), 0.02)

    def test_default_quote_has_three_tiers(self):
        result = calculate_quote({})

        self.assertEqual([tier["quantity"] for tier in result["tiers"]], [300, 500, 1000])
        self.assertEqual(result["tiers"][0]["total_cost_text"], "147.2元")
        self.assertEqual(result["tiers"][0]["exw_price_text"], "226.5元")
        self.assertEqual(result["tiers"][0]["fob_price_text"], "230.5元")
        self.assertEqual(result["tiers"][0]["margin_rate_text"], "35%")
        cb = result.get("cost_bridge")
        assert isinstance(cb, dict)
        self.assertEqual(cb["tier_quantity_ref"], 300)
        self.assertEqual(cb["addons_sum_per_pc"], 19.33)

    def test_invalid_quantities_fall_back_to_default(self):
        result = calculate_quote({"quantities": "abc,0,-1"})
        self.assertEqual([tier["quantity"] for tier in result["tiers"]], [300, 500, 1000])

    def test_sheet_calc_method_maps_to_calc_note_and_markdown_column(self):
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "DCF外料",
                        "calc_method": "侧片 + 底片 + 损耗15%",
                        "spec": "-",
                        "usage": "0.08码",
                        "unit_price": "450元/码",
                        "amount": 36.0,
                    },
                ],
            },
        )
        row = result["detail_rows"][0]
        self.assertEqual(row["calc_note"], "侧片 + 底片 + 损耗15%")
        self.assertIn("侧片", result["markdown"])

    def test_calc_note_cleans_engine_noise_before_display(self):
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "210D再生尼龙",
                        "calc_note": "系统推算：外包络≈0.098㎡÷默认门幅≈150cm→长约0.065m÷0.9144≈0.0712码→对齐用量0.07码（未计排版损耗；以业务细表为准）",
                        "spec": "58#",
                        "usage": "0.07码",
                        "unit_price": "12.5/码",
                        "amount": 0.89,
                    },
                ],
            },
        )
        note = result["detail_rows"][0]["calc_note"]
        self.assertNotIn("系统推算", note)
        self.assertNotIn("未计排版损耗", note)
        self.assertIn("外包络", note)

    def test_data_notice_packaging_hint_when_no_packaging_amount(self) -> None:
        """未列包装费时追加纸箱参考说明（不改金额）。"""
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "主料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    },
                ],
            },
        )
        self.assertIn("包装提示", result["data_notice"])
        self.assertIn("6", result["data_notice"])

    def test_data_notice_no_packaging_hint_when_pkg_line_has_amount(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "主料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    },
                    {
                        "name": "纸箱外卖",
                        "spec": "-",
                        "usage": "1",
                        "unit_price": "6元",
                        "amount": 6.0,
                    },
                ],
            },
        )
        self.assertNotIn("包装提示", result["data_notice"])

    def test_packaging_addon_per_piece_inserts_row(self) -> None:
        """未列包装费时可用 packaging_addon_per_piece 加计一行并入物料合计。"""
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "主料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    },
                ],
                "packaging_addon_per_piece": 7.0,
            },
        )
        self.assertNotIn("包装提示", result["data_notice"])
        self.assertAlmostEqual(float(result["material_total"]), 17.0, places=2)
        joined = " ".join(str(r.get("name") or "") for r in result["detail_rows"])
        self.assertIn("加计", joined)

    def test_packaging_estimated_from_product_size_is_in_cost(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "\u5851\u80f6\u6807\u51c6\u6263\u5177",
                        "spec": "-",
                        "usage": "2PCS",
                        "unit_price": "2.50\u5143/\u5957",
                        "amount": 5.0,
                    },
                ],
                "product_size": {
                    "length_cm": 21,
                    "height_cm": 12,
                    "width_cm": 6,
                },
                "mold_fee": 0,
                "processing_fee": 0,
                "system_overhead": 0,
            }
        )
        self.assertEqual(result["material_total"], 5.8)
        pkg = [r for r in result["detail_rows"] if "\u7eb8\u7bb1" in str(r.get("name") or "")]
        self.assertEqual(len(pkg), 1)
        self.assertEqual(pkg[0]["amount"], 0.8)
        self.assertIn("基础包装", pkg[0]["calc_note"])

    def test_packaging_estimate_large_product_size_band(self) -> None:
        """45×30×17cm 无显式包装行 → 偏大基础包装 2.00 元/个（非旧版外箱 8 元/个）。"""
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "主料",
                        "spec": "-",
                        "usage": "1码",
                        "unit_price": "10元/码",
                        "amount": 10.0,
                    },
                ],
                "product_size": {"length_cm": 45, "width_cm": 30, "height_cm": 17},
                "mold_fee": 0,
                "processing_fee": 0,
                "system_overhead": 0,
            }
        )
        self.assertAlmostEqual(float(result["material_total"]), 12.0, places=2)
        pkg = [r for r in result["detail_rows"] if "纸箱" in str(r.get("name") or "")]
        self.assertEqual(len(pkg), 1)
        self.assertAlmostEqual(float(pkg[0]["amount"]), 2.0, places=2)

    def test_reference_only_cost_row_is_not_priced_or_displayed(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "\u5851\u80f6\u6807\u51c6\u6263\u5177",
                        "spec": "-",
                        "usage": "2PCS",
                        "unit_price": "2.50\u5143/\u5957",
                        "amount": 5.0,
                    },
                    {
                        "name": "\u6210\u672c\u53c2\u8003",
                        "spec": "-",
                        "usage": "-",
                        "unit_price": "15\u5143/\u7801",
                        "amount": 0.0,
                    },
                ],
                "mold_fee": 0,
                "processing_fee": 0,
                "system_overhead": 0,
            }
        )
        self.assertEqual(result["material_total"], 5.0)
        names = [str(r.get("name") or "") for r in result["detail_rows"]]
        self.assertNotIn("\u6210\u672c\u53c2\u8003", names)

    def test_markdown_contains_required_tables(self):
        result = calculate_quote({})

        self.assertIn("### 明细数据表", result["markdown"])
        self.assertIn("### 三档数量报价", result["markdown"])
        self.assertIn("| 物料名称 | 计算方式 | 规格 | 用量 | 单价 | 小计 |", result["markdown"])
        md = result["markdown"]
        self.assertIn("| 数量 | 开模均摊 | 加工费 | 成本价（毛利前） | 预计毛利率 |", md)
        self.assertIn("毛利公式报价(EXW)", md)
        self.assertIn("| FOB报价（+4元/件） | EXW(USD) | FOB(USD) |", md)

    def test_management_loss_rate_scales_with_material_total(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {"name": "面料", "spec": "-", "usage": "-", "unit_price": "10元/m", "amount": 100.0},
                ],
                "management_loss_rate": 0.05,
            }
        )
        self.assertEqual(result["settings"]["system_overhead_rule"], "demand_pct_of_material_total")
        self.assertEqual(result["settings"]["system_overhead"], 5.0)

    def test_dimension_like_value_stays_in_spec_not_usage(self):
        result = calculate_quote(
            {
                "items": [
                    {"name": "面料", "spec": "140*90CM", "amount": 17},
                ]
            }
        )
        row = result["detail_rows"][0]
        self.assertEqual(row["spec"], "140*90CM")
        self.assertNotEqual(row["usage"], "140*90CM")
        self.assertAlmostEqual(float(row["amount"]), 17.0, places=2)

    def test_reconcile_unit_price_ignores_dimension_usage(self):
        from quote_engine import reconcile_row_amount_after_unit_price_change

        row = {
            "name": "盖内网袋",
            "spec": "140*90CM",
            "usage": "140*90CM",
            "unit_price": "11.5元/码",
            "amount": 2.0,
        }
        reconcile_row_amount_after_unit_price_change(
            row,
            old_unit_text="10元/码",
            old_amount=2.0,
        )
        self.assertAlmostEqual(float(row["amount"]), 2.3, places=2)
        self.assertNotAlmostEqual(float(row["amount"]), 1610.0, places=0)

    def test_fob_adds_four_yuan_per_piece(self):
        result = calculate_quote({})
        tier = result["tiers"][0]
        self.assertAlmostEqual(tier["fob_price"] - tier["exw_price"], 4.0, places=2)

    def test_include_fob_false_skips_fob_pricing(self):
        result = calculate_quote({"include_fob": False})
        self.assertFalse(result["include_fob"])
        self.assertIsNone(result["tiers"][0]["fob_price"])
        self.assertEqual(result["tiers"][0]["fob_price_text"], "")
        self.assertNotIn("FOB报价", result["markdown"])

    def test_exw_only_quote_has_cost_vat_derived_fields(self) -> None:
        """EXW-only（未报 FOB）：成本侧派生含税价，不改变 EXW 金额。"""
        result = calculate_quote({"include_fob": False})
        for tier in result["tiers"]:
            cbm = float(tier["cost_before_margin"])
            exp = round(cbm * 1.13, 2)
            self.assertEqual(tier["tax_rate"], 0.13)
            self.assertEqual(tier["tax_rate_text"], "13%")
            self.assertIsNotNone(tier["taxed_price"])
            self.assertAlmostEqual(float(tier["taxed_price"]), exp, places=2)
            from display_number_format import format_display_money_cny

            self.assertEqual(tier["taxed_price_text"], format_display_money_cny(exp))
        md = result["markdown"]
        self.assertIn("含税(13%，元/件)", md)

    def test_fob_quote_skips_numeric_taxed_price_but_keeps_label(self) -> None:
        """含 FOB 档位：不给出成本侧含税金额，仅文案说明。"""
        result = calculate_quote({"include_fob": True})
        t0 = result["tiers"][0]
        self.assertIsNone(t0["taxed_price"])
        self.assertEqual(t0["taxed_price_text"], "FOB口径：不加税")
        self.assertNotIn("含税(13%，元/件)", result["markdown"])

    def test_source_field_and_ai_marking_rule(self):
        result = calculate_quote({})
        kb_row = result["detail_rows"][0]
        ai_row = result["detail_rows"][2]

        self.assertEqual(kb_row["source"], "kb")
        self.assertEqual(ai_row["source"], "ai")

        # 规格/用量不应出现 AI 标注（由前端按 source 控制）。
        self.assertEqual(kb_row["spec_ai"], False)
        self.assertEqual(kb_row["usage_ai"], False)

        # 解析稳定前，markdown 不展示 AI 标注。
        self.assertNotIn("(AI)", result["markdown"])
        md = result["markdown"]
        for r in (kb_row, ai_row):
            self.assertIn(r["name"], md)
            self.assertIn(r["spec"], md)
            self.assertIn(r["usage"], md)
            self.assertIn(r["amount_text"], md)

    def test_data_notice_reports_sheet_anchor_gap(self) -> None:
        """表内底料锚点与明细合计差较大时追加对账短文（不改变金额）。"""
        result = calculate_quote(
            {
                "reference_prices": [
                    {
                        "kind": "sheet_material_subtotal",
                        "anchor_label": "底料",
                        "material_subtotal": 100.0,
                    },
                ],
                "items": [
                    {
                        "name": "简测试料",
                        "spec": "-",
                        "usage": "1个",
                        "unit_price": "10元/个",
                        "amount": 10.0,
                    },
                ],
            },
        )
        self.assertIn("对账提示", result["data_notice"])

    def test_detail_rows_get_accuracy_hints_for_unit_mismatch(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "外布",
                        "spec": "-",
                        "usage": "1.2㎡",
                        "unit_price": "18元/码",
                        "amount": 1.0,
                    },
                ],
            },
        )
        row = result["detail_rows"][0]
        self.assertEqual(row["unit_price"], "21.5元/㎡")
        self.assertAlmostEqual(float(row["amount"]), 25.83, places=2)
        self.assertIn("单位换算", row["calc_note"])
        self.assertEqual(row.get("raw_usage"), "1.2㎡")
        self.assertEqual(row.get("raw_unit_price"), "18元/码")
        self.assertTrue(row.get("unit_converted"))
        hints = row.get("accuracy_hints") or []
        self.assertTrue(any("原始用量单位与单价单位口径不一致" in str(h) for h in hints))
        """用量为 cm 且单价为元/米时，展示改为元/cm，小计不变；验算不误报。"""
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "拉链",
                        "spec": "-",
                        "usage": "30cm",
                        "unit_price": "3.5元/米",
                        "amount": 1.05,
                    },
                ],
            },
        )
        row = result["detail_rows"][0]
        self.assertEqual(row["unit_price"], "0元/cm")
        self.assertEqual(row.get("raw_unit_price"), "3.5元/米")
        self.assertAlmostEqual(float(row["amount"]), 1.05, places=2)
        hints = row.get("accuracy_hints") or []
        rough = any("粗略验算" in str(h) for h in hints)
        self.assertFalse(rough)
        self.assertIn("0元/cm", result["markdown"])

    def test_square_meter_usage_with_yard_price_is_converted_and_marked(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "0.14㎡",
                        "unit_price": "15元/码",
                        "amount": 0,
                    },
                ],
            },
        )
        row = result["detail_rows"][0]
        self.assertEqual(row["unit_price"], "17.9元/㎡")
        self.assertAlmostEqual(float(row["amount"]), 2.51, places=2)
        self.assertIn("单位换算", row["calc_note"])
        self.assertIn("17.9元/㎡", result["markdown"])

    def test_recalculates_stale_amount_when_usage_and_price_are_checkable(self) -> None:
        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "国产X-PAC",
                        "spec": "-",
                        "usage": "0.41码",
                        "unit_price": "50",
                        "amount": 15.0,
                    },
                ],
            },
        )

        row = result["detail_rows"][0]
        self.assertAlmostEqual(float(row["amount"]), 20.5, places=2)
        self.assertEqual(row["amount_text"], "20.5元")
        self.assertAlmostEqual(float(result["material_total"]), 20.5, places=2)


if __name__ == "__main__":
    unittest.main()
