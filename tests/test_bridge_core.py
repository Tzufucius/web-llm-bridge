import unittest

from tools.chatgpt_web_bridge.bridge_core import ChatGPTBridgeError, _BridgeRPCError


class BridgeErrorTests(unittest.TestCase):
    def test_safe_to_retry_survives_error_objects(self) -> None:
        rpc_error = _BridgeRPCError("TAB_CLOSED", "closed", safe_to_retry=True)
        bridge_error = ChatGPTBridgeError(
            "closed",
            "TAB_CLOSED",
            safe_to_retry=rpc_error.safe_to_retry,
        )
        self.assertTrue(rpc_error.safe_to_retry)
        self.assertTrue(bridge_error.safe_to_retry)

    def test_unknown_chat_state_is_not_retryable(self) -> None:
        error = ChatGPTBridgeError("unknown", "CHAT_STATE_UNKNOWN")
        self.assertFalse(error.safe_to_retry)


if __name__ == "__main__":
    unittest.main()
