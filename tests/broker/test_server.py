import unittest

from web_llm_bridge.broker.server import BrokerServer


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_params_have_structured_error(self) -> None:
        result = await BrokerServer().handle_request({"id": "1", "method": "open", "params": []})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    async def test_unknown_method_has_structured_error(self) -> None:
        result = await BrokerServer().handle_request({"id": "1", "method": "missing", "params": {}})
        self.assertEqual(result["error"]["code"], "UNKNOWN_METHOD")

    async def test_debug_trace_requires_request_id(self) -> None:
        result = await BrokerServer().handle_request({"id": "1", "method": "debug_trace", "params": {"session_id": "session"}})
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    async def test_wait_artifact_rejects_unbounded_timeout(self) -> None:
        result = await BrokerServer().handle_request({"id": "1", "method": "wait_artifact", "params": {"artifact_id": "img_test", "timeout_ms": 1}})
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
