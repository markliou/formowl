from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_mail.semantic_plan import deterministic_query_class, requires_workspace_evidence


class SemanticPlanRoutingTests(unittest.TestCase):
    def test_output_completion_is_non_exhaustive_across_source_families(self) -> None:
        ordinary_outputs = (
            "把周岑禾的設備維護郵件整理出來",
            "把林予安的驗收文件整理出來",
            "調閱周岑禾的設備維護郵件資料出來",
            "調閱林予安的驗收文件資料出來",
        )
        for prompt in ordinary_outputs:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    deterministic_query_class(prompt),
                    "evidence_lookup",
                )

        explicit_exact = (
            "列出周岑禾的所有設備維護郵件",
            "count 林予安的驗收文件",
            "inventory of project acceptance documents",
        )
        for prompt in explicit_exact:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    deterministic_query_class(prompt),
                    "exact_set_or_inventory",
                )

    def test_ordinary_conversation_does_not_require_workspace_evidence(self) -> None:
        ordinary_prompts = (
            "你好",
            "Hi there!",
            "How is your day?",
            "你好，今天天氣真不錯。",
            "Hey, hope your morning is going well.",
            "您好，最近還好嗎？",
            "請解釋什麼是知識圖譜",
            "What is email?",
            "請把這句翻譯成英文：我今天很忙",
            "請改寫這段文字：大家好",
        )

        for prompt in ordinary_prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(requires_workspace_evidence(prompt))

    def test_explicit_mail_or_workspace_requests_require_evidence(self) -> None:
        workspace_prompts = (
            "整理劉一帆的信件",
            "找我的信件",
            "列出所有信件",
            "Search my email for Liu Yifan",
            "What is the current supplier status?",
            "你好，請幫我找劉一帆寄來的信。",
            "Hi, search my inbox for the latest invoice.",
        )

        for prompt in workspace_prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(requires_workspace_evidence(prompt))

    def test_daily_greeting_and_chinese_mail_request_are_distinct_routes(self) -> None:
        self.assertFalse(requires_workspace_evidence("How is your day?"))
        self.assertTrue(requires_workspace_evidence("整理劉一帆的信件"))
        self.assertTrue(requires_workspace_evidence("查詢工作區的信件"))

    def test_chinese_mail_noun_variants_override_social_prefixes(self) -> None:
        prompts = (
            "您好，整理上週的來信。",
            "你好，列出昨天的寄出信。",
            "嗨，查一下寄出的信。",
            "Hello, 幫我找客戶寄來的信。",
            "你好，查看收到的信有哪些。",
            "您好，請找寄給客戶的那封信。",
            "你好，讀一下主管寄給我的信。",
            "嗨，搜尋會議相關郵件。",
            "你好，列出專案往來信。",
            "您好，看看最近的信件。",
            "你可以做什麼？先幫我找昨天的來信。",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(requires_workspace_evidence(prompt))

    def test_nonmail_source_requests_override_social_prefixes(self) -> None:
        prompts = (
            "Hi, find the project document",
            "你好，查詢專案資料",
            "Hello, retrieve the signed attachment.",
            "您好，整理上週的會議紀錄。",
            "Hey, show the open tickets.",
            "你好，列出相關檔案。",
            "How can you help? Search the repository for the incident report.",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(requires_workspace_evidence(prompt))

    def test_source_topic_without_lookup_remains_conversation(self) -> None:
        prompts = (
            "Hi, explain project management.",
            "你好，說明如何撰寫專案文件。",
            "Hey, write a short story about a lost document.",
            "你好，幫我找回信心。",
            "Hello, how is your day going?",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(requires_workspace_evidence(prompt))

    def test_bare_business_terms_do_not_force_mcp(self) -> None:
        ordinary_prompts = (
            "What is a supplier?",
            "Explain the data source.",
            "什麼是供應商？",
        )
        for prompt in ordinary_prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(requires_workspace_evidence(prompt))

    def test_terse_business_and_relation_requests_use_evidence(self) -> None:
        evidence_prompts = (
            "嘉值交期",
            "查詢嘉值交期",
            "查詢劉一帆與嘉值的關聯",
        )
        for prompt in evidence_prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(requires_workspace_evidence(prompt))

    def test_mail_noun_boundaries_do_not_turn_social_chat_into_lookup(self) -> None:
        prompts = (
            "你好，幫我找回信心。",
            "你好，幫我找回對未來信心。",
            "您好，我想找個方法改善彼此的信任。",
            "你好，說明如何查找網路信號。",
            "你好，請解釋什麼是來信。",
            "嗨，幫我寫一封信。",
            "你好，今天天氣真不錯。",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(requires_workspace_evidence(prompt))

    def test_prior_cited_evidence_can_be_reformatted_without_another_lookup(self) -> None:
        self.assertFalse(
            requires_workspace_evidence(
                "summarize the above in a table",
                prior_evidence_citeable=True,
                prior_evidence_present=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
