import unittest

from web_llm_bridge.providers.chatgpt import CHATGPT_PROVIDER


class ChatGPTProviderTests(unittest.TestCase):
    def test_definition_carries_capabilities_and_normalizes_url(self) -> None:
        self.assertTrue(CHATGPT_PROVIDER.capabilities["fullHistory"])
        self.assertEqual(CHATGPT_PROVIDER.normalize_url("https://chatgpt.com/c/a/?x=1"), "https://chatgpt.com/c/a")
