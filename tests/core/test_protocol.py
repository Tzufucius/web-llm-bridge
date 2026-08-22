import unittest

from web_llm_bridge.errors import WebLLMBridgeError
from web_llm_bridge.providers.chatgpt import CHATGPT_PROVIDER


class ProtocolTests(unittest.TestCase):
    def test_normalizes_query_and_fragment(self) -> None:
        self.assertEqual(CHATGPT_PROVIDER.normalize_url("https://www.chatgpt.com/c/a/?x=1#y"), "https://www.chatgpt.com/c/a")

    def test_invalid_url_is_structured(self) -> None:
        with self.assertRaises(WebLLMBridgeError) as caught:
            CHATGPT_PROVIDER.normalize_url("http://chatgpt.com/")
        self.assertEqual(caught.exception.code, "INVALID_URL")
