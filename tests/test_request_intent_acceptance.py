"""意图路由验收矩阵：真实口语样本 → 期望 route/dialog，并登记已知误判缺口。

仅新增测试，不修改 request_intent_router 主逻辑。
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from message_intent import classify_intent
from request_intent_router import (
    INTENT_COMPARE_QUOTE,
    INTENT_CONSULT_MATERIAL,
    INTENT_EXPLAIN_PRICE,
    INTENT_FALLBACK_GENERAL,
    INTENT_GENERATE_QUOTE,
    INTENT_MODIFY_PARAMS,
    INTENT_NEGOTIATE_PRICE,
    ROUTE_ADMIN_ACTION,
    ROUTE_CAPABILITY_HELP,
    ROUTE_CLARIFY,
    ROUTE_COMPARE_EXPLAIN,
    ROUTE_EXPLAIN,
    ROUTE_QA,
    ROUTE_QUOTE,
    ROUTE_QUOTE_PATCH,
    route_quote_request,
)


@dataclass(frozen=True)
class AcceptanceSample:
    sample_id: str
    user_prompt: str
    has_upload: bool
    has_active_quote: bool
    expected_route: str
    expected_dialog: str
    category: str = ""
    # 若当前实现与期望不一致且短期不修，填写实际路由用于登记缺口
    known_actual_route: str | None = None
    known_actual_dialog: str | None = None
    gap_reason: str = ""


def _route(user_prompt: str, *, has_upload: bool, has_active_quote: bool):
    return route_quote_request(
        {"user_prompt": user_prompt},
        has_upload=has_upload,
        has_active_quote=has_active_quote,
    )


# 30+ 条真实口语样本（含混合意图、无上下文、带附件语义、议价、对比、解释、改参）
ACCEPTANCE_SAMPLES: tuple[AcceptanceSample, ...] = (
    AcceptanceSample("S01", "帮我根据这个表直接报价", False, False, ROUTE_QUOTE, INTENT_GENERATE_QUOTE, "upload_quote"),
    AcceptanceSample("S02", "上传了表，顺便问600D是什么材料", True, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "upload_mixed_qa"),
    AcceptanceSample(
        "S03",
        "为什么图一是业务员算的你跟他算的不一样",
        False,
        True,
        ROUTE_COMPARE_EXPLAIN,
        INTENT_COMPARE_QUOTE,
        "compare_active",
    ),
    AcceptanceSample(
        "S04",
        "为什么图一是业务员算的你跟他算的不一样",
        True,
        False,
        ROUTE_CLARIFY,
        INTENT_FALLBACK_GENERAL,
        "upload_compare_no_session",
    ),
    AcceptanceSample("S05", "箱子改5元一个那么成本价是多少", False, True, ROUTE_QUOTE_PATCH, INTENT_MODIFY_PARAMS, "patch_fee"),
    AcceptanceSample("S06", "数量改300件", False, True, ROUTE_QUOTE_PATCH, INTENT_MODIFY_PARAMS, "patch_qty"),
    AcceptanceSample("S07", "这个报价为什么这么高", False, True, ROUTE_EXPLAIN, INTENT_EXPLAIN_PRICE, "explain_high"),
    AcceptanceSample("S08", "600D塔丝隆是什么材料", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "material_qa"),
    AcceptanceSample("S09", "旅行背包面料怎么选更耐磨", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "consult_backpack"),
    AcceptanceSample("S10", "这个多少钱", False, False, ROUTE_CLARIFY, INTENT_FALLBACK_GENERAL, "unclear_price"),
    AcceptanceSample("S11", "价格库怎么更新", False, False, ROUTE_ADMIN_ACTION, INTENT_FALLBACK_GENERAL, "admin"),
    AcceptanceSample("S12", "你有哪些功能", False, False, ROUTE_CAPABILITY_HELP, INTENT_FALLBACK_GENERAL, "capability"),
    AcceptanceSample(
        "S13",
        "别人报69.2，你算的差在哪",
        False,
        False,
        ROUTE_CLARIFY,
        INTENT_COMPARE_QUOTE,
        "compare_no_session",
        known_actual_route=ROUTE_CLARIFY,
        known_actual_dialog=INTENT_FALLBACK_GENERAL,
        gap_reason="L416-430：clarify 路由正确但 dialog_intent 未按 compare 语义标注",
    ),
    AcceptanceSample("S14", "别人报69.2，你算50.36，差在哪", False, True, ROUTE_COMPARE_EXPLAIN, INTENT_COMPARE_QUOTE, "compare_amount"),
    AcceptanceSample("S15", "客户觉得太贵了，有没有降档或国产替代方案", False, True, ROUTE_QA, INTENT_NEGOTIATE_PRICE, "negotiate_active"),
    AcceptanceSample(
        "S16",
        "换成便宜一点的材料会便宜多少",
        False,
        True,
        ROUTE_QUOTE_PATCH,
        INTENT_MODIFY_PARAMS,
        "material_trial",
        known_actual_route=ROUTE_QA,
        known_actual_dialog=INTENT_NEGOTIATE_PRICE,
        gap_reason="L250-253：议价信号(便宜)先于 patch/替料",
    ),
    AcceptanceSample(
        "S17",
        "这个材料有没有替代方案",
        False,
        False,
        ROUTE_QA,
        INTENT_CONSULT_MATERIAL,
        "substitute_consult",
        known_actual_route=ROUTE_QA,
        known_actual_dialog=INTENT_NEGOTIATE_PRICE,
        gap_reason="L95-98：替代方案命中 NEGOTIATE_RE，dialog 标成 negotiate",
    ),
    AcceptanceSample("S18", "这个报价能不能发给客户", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "business_send"),
    AcceptanceSample("S19", "客户问为什么贵怎么解释", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "explain_consult_no_quote"),
    AcceptanceSample("S20", "这张表有什么风险", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "risk"),
    AcceptanceSample("S21", "这个字段是什么意思", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "field_meaning"),
    AcceptanceSample(
        "S22",
        "尼龙双肩包500件多少钱",
        False,
        False,
        ROUTE_QUOTE,
        INTENT_GENERATE_QUOTE,
        "new_quote_text",
        known_actual_route=ROUTE_QA,
        known_actual_dialog=INTENT_CONSULT_MATERIAL,
        gap_reason="L307-308：BACKPACK/_looks_like_qa 先于 L320 quote_intent",
    ),
    AcceptanceSample("S23", "500件多少钱", False, True, ROUTE_QUOTE_PATCH, INTENT_MODIFY_PARAMS, "qty_trial_active"),
    AcceptanceSample("S24", "加工费怎么来的", False, True, ROUTE_EXPLAIN, INTENT_EXPLAIN_PRICE, "explain_fee"),
    AcceptanceSample(
        "S25",
        "和上次报价对比一下",
        False,
        True,
        ROUTE_COMPARE_EXPLAIN,
        INTENT_COMPARE_QUOTE,
        "compare_history",
        known_actual_route=ROUTE_QUOTE,
        known_actual_dialog=INTENT_GENERATE_QUOTE,
        gap_reason="L320-325：句中「报价」触发 business/quote_intent，压过 compare",
    ),
    AcceptanceSample("S26", "里料换涤纶试算500件", False, True, ROUTE_QUOTE_PATCH, INTENT_MODIFY_PARAMS, "material_patch"),
    AcceptanceSample("S27", "你好", False, False, ROUTE_CLARIFY, INTENT_FALLBACK_GENERAL, "greeting"),
    AcceptanceSample("S28", "帮我报价", False, False, ROUTE_QUOTE, INTENT_GENERATE_QUOTE, "explicit_quote"),
    AcceptanceSample("S29", "明细拆解一下", False, True, ROUTE_EXPLAIN, INTENT_EXPLAIN_PRICE, "explain_breakdown"),
    AcceptanceSample("S30", "面料对比尼龙和牛津", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "material_compare_qa"),
    AcceptanceSample("S31", "计算过程拆解一下", False, True, ROUTE_EXPLAIN, INTENT_EXPLAIN_PRICE, "explain_process"),
    AcceptanceSample("S32", "外箱单价改成3.5", False, True, ROUTE_QUOTE_PATCH, INTENT_MODIFY_PARAMS, "patch_unit"),
    AcceptanceSample("S33", "上传表并改数量300件", True, False, ROUTE_CLARIFY, INTENT_FALLBACK_GENERAL, "upload_patch_no_session"),
    AcceptanceSample("S34", "YKK拉链是什么", False, False, ROUTE_QA, INTENT_CONSULT_MATERIAL, "accessory_qa"),
    AcceptanceSample("S35", "能不能便宜一点还要防水", False, False, ROUTE_QA, INTENT_NEGOTIATE_PRICE, "negotiate_feature"),
    AcceptanceSample("S36", "500件多少钱", False, False, ROUTE_QUOTE, INTENT_GENERATE_QUOTE, "qty_new_quote"),
    AcceptanceSample(
        "S37",
        "28L尼龙双肩包500件帮我报价",
        False,
        False,
        ROUTE_QUOTE,
        INTENT_GENERATE_QUOTE,
        "explicit_new_quote",
        known_actual_route=ROUTE_QA,
        known_actual_dialog=INTENT_CONSULT_MATERIAL,
        gap_reason="同 S22：qa_signal 早于 quote_intent",
    ),
    AcceptanceSample(
        "S38",
        "为什么跟你算的不一样",
        False,
        True,
        ROUTE_EXPLAIN,
        INTENT_EXPLAIN_PRICE,
        "explain_dispute",
        known_actual_route=ROUTE_COMPARE_EXPLAIN,
        known_actual_dialog=INTENT_COMPARE_QUOTE,
        gap_reason="L247-248：compare 先于 explain（不一样+你算）",
    ),
    AcceptanceSample("S39", "对比业务员口径", False, True, ROUTE_COMPARE_EXPLAIN, INTENT_COMPARE_QUOTE, "compare_shorthand"),
    AcceptanceSample(
        "S40",
        "改一下",
        False,
        True,
        ROUTE_CLARIFY,
        INTENT_FALLBACK_GENERAL,
        "vague_patch",
        gap_reason="L341：低置信 clarify，未走 patch_missing_target",
    ),
)

# message_intent 层与 request_intent_router 期望不一致的登记（会话追问链路）
MESSAGE_INTENT_DIVERGENCE: tuple[tuple[str, bool, bool, str, str], ...] = (
    ("这个报价为什么这么高", False, True, "FOLLOW_UP", "request_router→explain"),
    ("为什么跟你算的不一样", False, True, "FOLLOW_UP", "request_router→compare_explain(实际)"),
    ("和上次报价对比一下", False, True, "COMPARE", "request_router→quote(实际)"),
    ("加工费怎么来的", False, True, "CHAT", "request_router→explain"),
    ("客户觉得太贵了，有没有降档或国产替代方案", False, True, "NEW_QUOTE", "request_router→qa/negotiate"),
)


class IntentAcceptanceSpecTest(unittest.TestCase):
    """期望路由：无 known_actual_* 的样本必须命中 spec。"""

    def test_samples_match_spec(self) -> None:
        for sample in ACCEPTANCE_SAMPLES:
            if sample.known_actual_route:
                continue
            with self.subTest(sample_id=sample.sample_id, prompt=sample.user_prompt):
                route = _route(
                    sample.user_prompt,
                    has_upload=sample.has_upload,
                    has_active_quote=sample.has_active_quote,
                )
                d = route.as_dict()["dialog_intent"]
                self.assertEqual(route.route_intent, sample.expected_route, route.route_reason)
                self.assertEqual(d, sample.expected_dialog)

    def test_documented_gaps_remain_stable(self) -> None:
        """登记已知误判：防止无意修复前缺少回归感知。"""
        gaps = [s for s in ACCEPTANCE_SAMPLES if s.known_actual_route]
        self.assertGreaterEqual(len(gaps), 5)
        for sample in gaps:
            with self.subTest(sample_id=sample.sample_id, reason=sample.gap_reason):
                route = _route(
                    sample.user_prompt,
                    has_upload=sample.has_upload,
                    has_active_quote=sample.has_active_quote,
                )
                d = route.as_dict()["dialog_intent"]
                self.assertEqual(route.route_intent, sample.known_actual_route)
                if sample.known_actual_dialog:
                    self.assertEqual(d, sample.known_actual_dialog)
                self.assertNotEqual(
                    (route.route_intent, d),
                    (sample.expected_route, sample.expected_dialog),
                    "gap 已修复，请改样本期望并移除 known_actual",
                )


class IntentAcceptanceGapAuditTest(unittest.TestCase):
    """审计：打印级登记——期望 vs 实际（用于验收报告，不断言失败）。"""

    def test_audit_matrix_non_gap_samples(self) -> None:
        mismatches = []
        for sample in ACCEPTANCE_SAMPLES:
            route = _route(
                sample.user_prompt,
                has_upload=sample.has_upload,
                has_active_quote=sample.has_active_quote,
            )
            d = route.as_dict()["dialog_intent"]
            ok = route.route_intent == sample.expected_route and d == sample.expected_dialog
            if not ok and not sample.known_actual_route:
                mismatches.append(
                    f"{sample.sample_id}: exp={sample.expected_route}/{sample.expected_dialog} "
                    f"got={route.route_intent}/{d} reason={route.route_reason}"
                )
        self.assertEqual(mismatches, [], "\n".join(mismatches))


class MessageIntentLayerDivergenceTest(unittest.TestCase):
    """server.handle_session_intent_quote 使用 classify_intent，与 request 路由可能分叉。"""

    def test_divergence_cases_documented(self) -> None:
        for text, has_upload, has_session, expected_mi, note in MESSAGE_INTENT_DIVERGENCE:
            with self.subTest(prompt=text, note=note):
                got = classify_intent(
                    text,
                    has_new_upload=has_upload,
                    has_session_quote=has_session,
                )
                self.assertEqual(got, expected_mi)


if __name__ == "__main__":
    unittest.main()
