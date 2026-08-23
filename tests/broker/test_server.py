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

    async def test_removed_methods_are_unknown(self) -> None:
        for method in ("debug_trace", "debug_snapshot", "wait_artifact", "resolve_artifact"):
            result = await BrokerServer().handle_request({"id": "1", "method": method, "params": {}})
            self.assertEqual(result["error"]["code"], "UNKNOWN_METHOD")

    async def test_close_requires_explicit_session_id(self) -> None:
        result = await BrokerServer().handle_request({"id": "1", "method": "close_session", "params": {}})
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
