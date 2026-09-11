import unittest
from unittest.mock import Mock, patch

from invest_assistant import config
from invest_assistant.recommendations import briefing as llm_briefing


class LlmRequestTimeoutTests(unittest.TestCase):
    """The macro-issues briefing timed out at the previously hardcoded 60s in two separate
    real runs (the 2026-09-09 cron and the 2026-09-08 report rebuild) while shorter calls in
    the same runs succeeded -- see config.LLM_REQUEST_TIMEOUT_SEC."""

    def test_call_uses_configured_timeout(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with patch.object(config, "LLM_API_KEY", "k"), \
                patch.object(config, "LLM_REQUEST_TIMEOUT_SEC", 180), \
                patch.object(llm_briefing.requests, "post", return_value=response) as post:
            llm_briefing._call_chat("system", "user")
        self.assertEqual(post.call_args.kwargs["timeout"], 180)

    def test_default_leaves_room_for_the_macro_issues_briefing(self):
        self.assertGreaterEqual(config.LLM_REQUEST_TIMEOUT_SEC, 180)


if __name__ == "__main__":
    unittest.main()
