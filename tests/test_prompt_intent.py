import unittest

from prompt_intent import user_prompt_has_quote_intent


class TestPromptIntent(unittest.TestCase):
    def test_empty_not_intent(self) -> None:
        self.assertFalse(user_prompt_has_quote_intent(""))
        self.assertFalse(user_prompt_has_quote_intent("   "))

    def test_greeting_not_intent(self) -> None:
        self.assertFalse(user_prompt_has_quote_intent("你好"))
        self.assertFalse(user_prompt_has_quote_intent("您好！"))
        self.assertFalse(user_prompt_has_quote_intent("谢谢"))
        self.assertFalse(user_prompt_has_quote_intent("在吗"))

    def test_substantive_intent(self) -> None:
        self.assertTrue(user_prompt_has_quote_intent("需要一款28L背包，数量1200，按FOB报"))
        self.assertTrue(user_prompt_has_quote_intent("尼龙面料双肩包多少钱"))
        self.assertTrue(user_prompt_has_quote_intent("订500件，含拉链和里布"))


if __name__ == "__main__":
    unittest.main()
