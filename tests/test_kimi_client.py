import json
import os
import unittest
from unittest.mock import patch

from kimi_client import (
    _backfill_amount_from_unit_price,
    _looks_like_quantity_ladder,
    _openai_messages_have_vision,
    _parse_compound_piece_set_price,
    _sanitize_row_amount_for_price_usage_mismatch,
    build_endpoint_candidates,
    get_kimi_config,
    get_kimi_status,
)
from material_inference import PENDING_INFERENCE_USAGE_FALLBACK
from llm_audit import LlmAuditCollector, _collect_llm_amount_rejections, diff_merge_fields

_API_KEY_ENVS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "KIMI_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENCLAW_API_KEY",
    "API_KEY",
)


class KimiClientTest(unittest.TestCase):
    def test_build_endpoint_candidates_never_uses_messages_path(self):
        eps = build_endpoint_candidates(
            "https://example.com/v1",
            api_key_source="OPENAI_API_KEY",
        )
        self.assertEqual(eps, ["https://example.com/v1/chat/completions"])
        self.assertTrue(all("/messages" not in ep for ep in eps))

    def test_build_endpoint_candidates_moonshot_dual_region(self):
        eps = build_endpoint_candidates("https://api.moonshot.ai/v1")
        self.assertGreaterEqual(len(eps), 2)
        joined = " ".join(eps)
        self.assertIn("moonshot.ai", joined)
        self.assertIn("moonshot.cn", joined)

    def test_status_disabled_without_api_key(self):
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        try:
            status = get_kimi_status()
            self.assertFalse(status["enabled"])
            self.assertIn("last_call_success", status)
            self.assertIn("last_call_error", status)
        finally:
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val

    def test_openai_messages_have_vision_detects_image(self):
        self.assertTrue(
            _openai_messages_have_vision(
                [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]}]
            )
        )

    def test_diff_merge_fields_tracks_kb_price_rejection(self):
        before = [{"name": "拉链", "kb_hit": True, "unit_price": "7元/条", "usage": "-"}]
        after = [{"name": "拉链", "kb_hit": True, "unit_price": "7元/条", "usage": "1条", "usage_ai": True}]
        accepted, rejected = diff_merge_fields(before, after)
        self.assertIn("usage", accepted)
        self.assertNotIn("unit_price_when_kb_hit", rejected)

    def test_llm_audit_collector_builds_payload(self):
        col = LlmAuditCollector()
        col.seed_from_status({"provider": "openai-compatible", "model": "gpt-5.5", "enabled": True})
        col.record_stage("demand_completion", {"used": True, "error": "", "duration_ms": 50}, input_rows=2, output_rows=2)
        audit = col.to_dict()
        self.assertEqual(audit["final_truth_source"], "local_formula_calculate_quote")
        self.assertFalse(audit["model_overrides_final_price"])
        self.assertEqual(audit["calls"][0]["stage"], "demand_completion")

    def test_model_amount_not_written_to_row_amount(self):
        from kimi_client import _merge_demand_rows

        source = [{"name": "拉链", "unit_price": "7元/条", "usage": "-", "amount": 0, "kb_hit": True}]
        ai_rows = [{"usage": "1条", "unit_price": "7元/条", "amount": 99.0, "usage_ai": True, "amount_ai": True}]
        merged = _merge_demand_rows(source, ai_rows)
        self.assertEqual(merged[0].get("llm_suggested_amount"), 99.0)
        self.assertNotEqual(float(merged[0].get("amount") or 0), 99.0)
        self.assertFalse(merged[0].get("amount_ai"))

    def test_model_amount_rejection_in_audit_diff(self):
        before = [{"name": "布", "usage": "-", "unit_price": "10元/码", "amount": 0}]
        after = [
            {
                "name": "布",
                "usage": "1码",
                "unit_price": "10元/码",
                "amount": 10.0,
                "usage_ai": True,
                "llm_suggested_amount": 25.0,
            }
        ]
        accepted, rejected = diff_merge_fields(before, after)
        self.assertIn("usage", accepted)
        rejected = sorted(set(rejected) | set(_collect_llm_amount_rejections(after)))
        self.assertIn("final_amount_must_be_local_formula", rejected)

    def test_material_total_ignores_llm_suggested_amount(self):
        from quote_engine import calculate_quote

        result = calculate_quote(
            {
                "items": [
                    {
                        "name": "测试料",
                        "spec": "-",
                        "usage": "1个",
                        "unit_price": "10元/个",
                        "amount": 10.0,
                        "llm_suggested_amount": 999.0,
                    }
                ],
                "include_fob": False,
            }
        )
        self.assertAlmostEqual(float(result["material_total"]), 10.0, places=2)

    def test_base_llm_status_openai_compatible_provider(self):
        from kimi_client import KimiConfig, _base_llm_status

        cfg = KimiConfig(
            api_key="sk-openai-test",
            api_key_source="OPENAI_API_KEY",
            base_url="https://code.codingplay.top/redeem/v1",
            model="gpt-5.5",
            timeout_s=25,
            temperature=1.0,
        )
        st = _base_llm_status(cfg)
        self.assertEqual(st["provider"], "openai-compatible")
        self.assertEqual(st["model"], "gpt-5.5")
        self.assertEqual(st["endpoint"], "https://code.codingplay.top/redeem/v1/chat/completions")

    def test_anthropic_not_auto_selected_without_llm_provider(self):
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "ANTHROPIC_BASE_URL": os.environ.pop("ANTHROPIC_BASE_URL", None),
            "ANTHROPIC_MODEL": os.environ.pop("ANTHROPIC_MODEL", None),
            "KIMI_MODEL": os.environ.pop("KIMI_MODEL", None),
            "MOONSHOT_MODEL": os.environ.pop("MOONSHOT_MODEL", None),
            "LLM_PROVIDER": os.environ.pop("LLM_PROVIDER", None),
        }
        try:
            os.environ.update(
                {
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                    "ANTHROPIC_BASE_URL": "https://api.anthropic.com/v1",
                    "ANTHROPIC_MODEL": "claude-opus-4-7",
                    "KIMI_MODEL": "kimi-k2.6",
                }
            )
            cfg = get_kimi_config()
            self.assertNotEqual(cfg.api_key_source, "ANTHROPIC_API_KEY")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_build_llm_health_report_config_only(self):
        from kimi_client import build_llm_health_report

        report = build_llm_health_report(live_probe=False)
        self.assertIn(report["status"], {"config_only", "missing_api_key"})
        self.assertIn("provider", report)
        self.assertIn("endpoint", report)
        self.assertIn("api_key_masked", report)
        key = str(report.get("api_key_masked") or "")
        if key:
            self.assertNotIn("sk-ant-api", key)
            self.assertIn("…", key)

    def test_compound_piece_set_price_not_quantity_ladder(self):
        txt = "1.3/0.5/SET"
        self.assertAlmostEqual(float(_parse_compound_piece_set_price(txt) or 0), 1.8)
        self.assertFalse(_looks_like_quantity_ladder(txt.lower()))

    def test_backfill_compound_set_without_usage_multiplies_once(self):
        row = {"name": "口字扣", "usage": "-", "unit_price": "1.3/0.5/SET", "amount": 0}
        _backfill_amount_from_unit_price(row)
        self.assertEqual(row["amount"], 1.8)

    def test_backfill_yard_price_with_meter_usage_converts(self):
        row = {
            "name": "拉链",
            "usage": "0.68米",
            "unit_price": "0.3/Y",
            "amount": 0,
        }
        _sanitize_row_amount_for_price_usage_mismatch(row)
        # 0.68m -> ~0.744 yd -> *0.3
        self.assertAlmostEqual(row["amount"], round(0.68 / 0.9144 * 0.3, 2), places=2)

    def test_backfill_meter_price_with_cm_usage_converts(self):
        row = {"name": "彩色圆绳提手", "usage": "30cm", "unit_price": "3.5元/米", "amount": 0}
        _backfill_amount_from_unit_price(row)
        self.assertAlmostEqual(float(row["amount"]), 1.05, places=2)

    def test_area_m2_usage_with_linear_yard_price_needs_roll_width(self):
        row = {
            "name": "210D涤纶",
            "spec": "152cm",
            "usage": "152cm / 0.21399㎡",
            "unit_price": "10.5元/码",
            "amount": 0,
        }
        _sanitize_row_amount_for_price_usage_mismatch(row)
        yds = (0.21399 / 1.52) / 0.9144
        self.assertAlmostEqual(row["amount"], round(yds * 10.5, 2), places=2)

    def test_sanitize_missing_usage_linear_price_removes_fake_amount(self):
        row = {"usage": "-", "unit_price": "480元/码", "amount": 480}
        _sanitize_row_amount_for_price_usage_mismatch(row)
        self.assertNotIn("amount", row)

    def test_sanitize_zero_yard_usage_backfills_amount_zero(self):
        row = {"usage": "0码", "unit_price": "480元/码", "amount": 480}
        _sanitize_row_amount_for_price_usage_mismatch(row)
        self.assertEqual(row.get("amount"), 0.0)

    def test_backfill_decimal_yard_exact(self):
        row = {"usage": "0.774码", "unit_price": "480元/码", "amount": 0}
        _backfill_amount_from_unit_price(row)
        self.assertAlmostEqual(row["amount"], round(0.774 * 480, 2), places=2)

    def test_sanitize_area_price_overrides_bad_ai_amount(self):
        row = {
            "name": "x-pac",
            "usage": "0.41㎡",
            "unit_price": "50元/码²",
            "amount": 32.8,
        }
        _sanitize_row_amount_for_price_usage_mismatch(row)
        self.assertAlmostEqual(row["amount"], round(50 * (0.41 / 0.83612736), 2), places=2)

    def test_backfill_overrides_bad_ai_amount_when_formula_is_direct(self):
        row = {
            "name": "X-PAC主体面料",
            "usage": "0.41",
            "unit_price": "50元/码",
            "amount": 26.0,
        }
        _backfill_amount_from_unit_price(row)
        self.assertAlmostEqual(row["amount"], 20.5, places=2)

    def test_dch_implicit_roll_sqyd_when_no_explicit_width(self):
        """DCH：元/码² × 线码，无幅宽时对粗苯外行采用默认卷材幅宽约 148cm。"""
        row = {
            "name": "3.2oz DCH",
            "usage": "1码",
            "unit_price": "95元/码²",
            "amount": 0,
            "calc_note": "并入工艺备注（非独立用料）",
        }
        _backfill_amount_from_unit_price(row)
        self.assertGreater(float(row.get("amount") or 0), 80.0)

    def test_reconcile_zeros_secondary_dyneema_when_primary_row_paid(self):
        from kimi_client import reconcile_fabric_charge_totals

        items = [
            {"name": "3.2oz DCH", "usage": "1码²", "spec": "", "unit_price": "95元/码²", "amount": 95.0},
            {
                "name": "夹层3.2oz DCH示意",
                "calc_note": "非独立用料",
                "usage": "说明末尾 / 1码",
                "spec": "幅宽148CM",
                "unit_price": "95元/码²",
                "amount": 200.0,
            },
        ]
        reconcile_fabric_charge_totals(items)
        self.assertAlmostEqual(float(items[1].get("amount") or 0), 0.0, places=2)

    def test_reconcile_standalone_secondary_still_backfills_from_prose(self):
        from kimi_client import reconcile_fabric_charge_totals

        items = [
            {
                "name": "3.2oz DCH",
                "calc_note": "非独立用料；仅本条",
                "usage": "工艺说明末尾 / 1码",
                "spec": "幅宽148CM",
                "unit_price": "95元/码²",
                "amount": 0,
            },
        ]
        reconcile_fabric_charge_totals(items)
        self.assertGreater(float(items[0].get("amount") or 0), 10.0)

    def test_market_estimate_meta_for_structure_pending_row(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "插扣（结构待核）",
                    "usage": "2个",
                    "unit_price": "-",
                    "from_bag_structure_extraction": True,
                    "recognition_status": "candidate_review",
                }
            ]
        )
        self.assertTrue(rows[0].get("unit_price_ai"))
        self.assertTrue(rows[0].get("amount_ai"))
        self.assertIn(MARKET_ESTIMATE_NOTE, str(rows[0].get("calc_note") or ""))

    def test_kb_hit_price_not_overwritten_by_market_estimate_meta(self) -> None:
        from kimi_client import _apply_market_estimate_row_meta

        row = {
            "name": "普通拉头",
            "unit_price": "0.3元/个",
            "kb_hit": True,
            "from_bag_structure_extraction": True,
        }
        _apply_market_estimate_row_meta(row)
        self.assertFalse(row.get("unit_price_ai"))
        self.assertFalse(row.get("amount_ai"))

    def test_kb_hit_invalid_unit_price_gets_market_estimate(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "6分D扣 2个",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": True,
                    "recognition_status": "matched",
                    "recognition_reason": "知识库命中",
                    "kb_matched_name": "6分D扣",
                }
            ]
        )
        row = rows[0]
        self.assertIn("元/个", str(row.get("unit_price") or ""))
        self.assertTrue(row.get("unit_price_ai"))
        self.assertTrue(row.get("amount_ai"))
        self.assertEqual(row.get("source"), "ai")
        self.assertFalse(row.get("kb_hit"))
        self.assertIn(MARKET_ESTIMATE_NOTE, str(row.get("calc_note") or ""))

    def test_kb_hit_valid_unit_price_keeps_kb_not_ai(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "普通拉头",
                    "usage": "1个",
                    "unit_price": "0.3元/个",
                    "amount": 0.3,
                    "kb_hit": True,
                    "recognition_status": "matched",
                }
            ]
        )
        row = rows[0]
        self.assertEqual(row.get("unit_price"), "0.3元/个")
        self.assertEqual(row.get("source"), "kb")
        self.assertFalse(row.get("unit_price_ai"))
        self.assertNotIn(MARKET_ESTIMATE_NOTE, str(row.get("calc_note") or ""))


    def test_chinese_split_row_gets_local_market_price_and_amount(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "\u0036\u5206D\u6263 \u0032\u4e2a",
                    "usage": "\u0032\u4e2a",
                    "unit_price": "-",
                    "kb_hit": False,
                    "recognition_status": "split",
                    "_source_combined_name": "\u0036\u5206D\u6263 \u0032\u4e2a\u0036\u5206\u68af\u6263 \u0034\u4e2a",
                }
            ]
        )
        self.assertTrue(rows[0].get("unit_price_ai"))
        self.assertTrue(rows[0].get("amount_ai"))
        self.assertIn("\u5143/\u4e2a", str(rows[0].get("unit_price") or ""))
        self.assertGreater(float(rows[0].get("amount") or 0), 0)
        self.assertIn(MARKET_ESTIMATE_NOTE, str(rows[0].get("calc_note") or ""))

    def test_kb_hit_split_row_keeps_kb_price_and_extracts_name_usage(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "6分D扣 2个",
                    "usage": "-",
                    "unit_price": "0.3元/个",
                    "kb_hit": True,
                    "recognition_status": "split",
                    "_source_combined_name": "6分D扣 2个6分梯扣 4个",
                    "amount": 0,
                }
            ]
        )

        row = rows[0]
        self.assertEqual(row.get("usage"), "2个")
        self.assertEqual(row.get("unit_price"), "0.3元/个")
        self.assertAlmostEqual(float(row.get("amount") or 0), 0.6, places=2)
        self.assertEqual(row.get("source"), "kb")
        self.assertFalse(row.get("unit_price_ai"))
        self.assertNotIn(MARKET_ESTIMATE_NOTE, str(row.get("calc_note") or ""))

    def test_non_kb_split_row_still_gets_market_estimate_flags(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "胸带调节扣 2个",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": False,
                    "recognition_status": "split",
                    "_source_combined_name": "胸带调节扣 2个6分D扣 2个",
                }
            ]
        )

        row = rows[0]
        self.assertEqual(row.get("usage"), "2个")
        self.assertTrue(row.get("unit_price_ai"))
        self.assertTrue(row.get("amount_ai"))
        self.assertEqual(row.get("source"), "ai")
        self.assertGreater(float(row.get("amount") or 0), 0)
        self.assertIn(MARKET_ESTIMATE_NOTE, str(row.get("calc_note") or ""))

    def test_chinese_structure_pending_row_gets_usage_price_and_amount(self) -> None:
        from kimi_client import MARKET_ESTIMATE_NOTE, _apply_local_price_fallback

        rows = _apply_local_price_fallback(
            [
                {
                    "name": "\u8170\u5c01\uff08\u7ed3\u6784\u5f85\u6838\uff09",
                    "usage": "-",
                    "unit_price": "-",
                    "kb_hit": False,
                    "from_bag_structure_extraction": True,
                    "recognition_status": "candidate_review",
                }
            ]
        )
        row = rows[0]
        self.assertEqual(row.get("usage"), PENDING_INFERENCE_USAGE_FALLBACK)
        self.assertTrue(row.get("usage_ai"))
        self.assertTrue(row.get("unit_price_ai"))
        self.assertIn("元/", str(row.get("unit_price") or ""))
        self.assertEqual(float(row.get("amount") or 0), 0.0)
        self.assertTrue(row.get("exclude_from_cost"))
        self.assertIn(MARKET_ESTIMATE_NOTE, str(row.get("calc_note") or ""))

    def test_openai_api_key_priority_over_anthropic(self) -> None:
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "OPENAI_BASE_URL": os.environ.pop("OPENAI_BASE_URL", None),
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
            "ANTHROPIC_BASE_URL": os.environ.pop("ANTHROPIC_BASE_URL", None),
            "ANTHROPIC_MODEL": os.environ.pop("ANTHROPIC_MODEL", None),
        }
        try:
            os.environ.update(
                {
                    "OPENAI_API_KEY": "sk-openai-test",
                    "OPENAI_MODEL": "gpt-5.5",
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                    "ANTHROPIC_MODEL": "claude-opus-4-7",
                }
            )
            cfg = get_kimi_config()
            status = get_kimi_status()
            self.assertEqual(cfg.api_key_source, "OPENAI_API_KEY")
            self.assertEqual(cfg.model, "gpt-5.5")
            self.assertEqual(status["provider"], "openai")
            self.assertEqual(status["api_key_source"], "OPENAI_API_KEY")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_llm_provider_anthropic_does_not_switch_provider(self) -> None:
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "LLM_PROVIDER": os.environ.pop("LLM_PROVIDER", None),
            "QUOTE_LLM_PROVIDER": os.environ.pop("QUOTE_LLM_PROVIDER", None),
            "OPENAI_BASE_URL": os.environ.pop("OPENAI_BASE_URL", None),
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
            "ANTHROPIC_BASE_URL": os.environ.pop("ANTHROPIC_BASE_URL", None),
            "ANTHROPIC_MODEL": os.environ.pop("ANTHROPIC_MODEL", None),
        }
        try:
            os.environ.update(
                {
                    "LLM_PROVIDER": "anthropic",
                    "OPENAI_API_KEY": "sk-openai-test",
                    "OPENAI_MODEL": "gpt-5.5",
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                    "ANTHROPIC_BASE_URL": "https://api.anthropic.com/v1",
                    "ANTHROPIC_MODEL": "claude-opus-4-7",
                }
            )
            cfg = get_kimi_config()
            status = get_kimi_status()
            self.assertEqual(cfg.api_key_source, "OPENAI_API_KEY")
            self.assertEqual(cfg.model, "gpt-5.5")
            self.assertEqual(status["provider"], "openai")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_llm_provider_claude_does_not_read_claude_api_key(self) -> None:
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "LLM_PROVIDER": os.environ.pop("LLM_PROVIDER", None),
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
        }
        try:
            os.environ.update(
                {
                    "LLM_PROVIDER": "claude",
                    "CLAUDE_API_KEY": "sk-claude-test",
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                }
            )
            cfg = get_kimi_config()
            self.assertEqual(cfg.api_key, "")
            self.assertEqual(cfg.api_key_source, "")
            self.assertEqual(cfg.model, "gpt-5.3-codex")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_only_openai_api_key_is_read(self) -> None:
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
            "OPENAI_BASE_URL": os.environ.pop("OPENAI_BASE_URL", None),
        }
        try:
            os.environ.update(
                {
                    "KIMI_API_KEY": "sk-kimi-test",
                    "MOONSHOT_API_KEY": "sk-moonshot-test",
                    "DEEPSEEK_API_KEY": "sk-deepseek-test",
                    "OPENCLAW_API_KEY": "sk-openclaw-test",
                    "API_KEY": "sk-generic-test",
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                    "CLAUDE_API_KEY": "sk-claude-test",
                }
            )
            cfg = get_kimi_config()
            self.assertEqual(cfg.api_key, "")
            self.assertEqual(cfg.api_key_source, "")
            self.assertEqual(cfg.model, "gpt-5.3-codex")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_openai_endpoint_candidates_use_chat_completions(self) -> None:
        eps = build_endpoint_candidates(
            "https://api.openai.com/v1",
            api_key_source="OPENAI_API_KEY",
        )
        self.assertEqual(eps, ["https://api.openai.com/v1/chat/completions"])

    def test_classify_http_error_invalid_model(self) -> None:
        from kimi_client import _classify_http_error, _openai_model_error_hint

        code = _classify_http_error(400, '{"error":{"message":"The model `gpt-5.5` does not exist"}}')
        self.assertEqual(code, "invalid_model")
        self.assertIn("OPENAI_MODEL", _openai_model_error_hint(code))

    def test_send_openai_chat_request_mock(self) -> None:
        from kimi_client import send_chat_request

        captured: dict = {}

        def fake_open(req, timeout=30):
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))

            class Resp:
                def read(self):
                    return json.dumps(
                        {"choices": [{"message": {"content": "OK"}}]}
                    ).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return Resp()

        with patch("kimi_client.request.urlopen", side_effect=fake_open):
            raw = send_chat_request(
                endpoint="https://api.openai.com/v1/chat/completions",
                api_key="sk-openai-test",
                body={
                    "model": "gpt-5.5",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_completion_tokens": 8,
                },
                timeout_s=5,
                disable_proxy=False,
            )
        payload = json.loads(raw)
        self.assertEqual(payload["choices"][0]["message"]["content"], "OK")
        self.assertIn("authorization", captured["headers"])
        self.assertNotIn("x-api-key", captured["headers"])
        self.assertNotIn("anthropic-version", captured["headers"])
        self.assertEqual(captured["body"]["model"], "gpt-5.5")

    def test_build_llm_health_report_invalid_model(self) -> None:
        from kimi_client import build_llm_health_report

        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "OPENAI_BASE_URL": os.environ.pop("OPENAI_BASE_URL", None),
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
        }
        try:
            os.environ["OPENAI_API_KEY"] = "sk-openai-test"
            os.environ["OPENAI_MODEL"] = "gpt-5.5"

            def fake_open(req, timeout=30):
                import urllib.error

                raise urllib.error.HTTPError(
                    req.full_url,
                    400,
                    "Bad Request",
                    hdrs=None,
                    fp=type(
                        "F",
                        (),
                        {
                            "read": lambda self: json.dumps(
                                {"error": {"message": "invalid model gpt-5.5"}}
                            ).encode("utf-8")
                        },
                    )(),
                )

            with patch("kimi_client.request.urlopen", side_effect=fake_open):
                report = build_llm_health_report(live_probe=True)
            self.assertEqual(report["provider"], "openai")
            self.assertEqual(report["model"], "gpt-5.5")
            self.assertEqual(report["api_key_source"], "OPENAI_API_KEY")
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["error"], "invalid_model")
            self.assertIn("OPENAI_MODEL", str(report.get("error_hint") or ""))
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_redeploy_script_requires_openai_api_key(self) -> None:
        from pathlib import Path

        text = Path(__file__).resolve().parents[1].joinpath("scripts/redeploy_server.sh").read_text(
            encoding="utf-8"
        )
        norm = text.replace("\r\n", "\n")
        self.assertIn('OPENAI_API_KEY:-}" && -z "${MOONSHOT_API_KEY', norm)
        self.assertNotIn("ANTHROPIC_API_KEY", norm)

    def test_openai_relay_base_url_builds_chat_completions(self) -> None:
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "OPENAI_BASE_URL": os.environ.pop("OPENAI_BASE_URL", None),
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
        }
        try:
            os.environ.update(
                {
                    "OPENAI_API_KEY": "sk-openai-test",
                    "OPENAI_BASE_URL": "https://code.codingplay.top/redeem",
                    "OPENAI_MODEL": "gpt-5.5",
                }
            )
            cfg = get_kimi_config()
            eps = build_endpoint_candidates(cfg.base_url, api_key_source=cfg.api_key_source)
            self.assertEqual(cfg.model, "gpt-5.5")
            self.assertEqual(eps[0], "https://code.codingplay.top/redeem/v1/chat/completions")
            self.assertEqual(get_kimi_status()["provider"], "openai-compatible")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val

    def test_default_openai_model_is_gpt_53_codex_without_env(self) -> None:
        saved = {name: os.environ.pop(name, None) for name in _API_KEY_ENVS}
        extra = {
            "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
            "OPENAI_BASE_URL": os.environ.pop("OPENAI_BASE_URL", None),
        }
        try:
            os.environ["OPENAI_API_KEY"] = "sk-openai-test"
            cfg = get_kimi_config()
            self.assertEqual(cfg.model, "gpt-5.3-codex")
        finally:
            for name in list(_API_KEY_ENVS) + list(extra):
                os.environ.pop(name, None)
            for name, val in saved.items():
                if val is not None:
                    os.environ[name] = val
            for name, val in extra.items():
                if val is not None:
                    os.environ[name] = val


if __name__ == "__main__":
    unittest.main()
