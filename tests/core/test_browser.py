import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from web_llm_bridge.browser import BrowserBootstrap, BrowserLauncher
from web_llm_bridge.errors import BrowserLaunchError, RPCError
from web_llm_bridge.protocol import BROWSER_HANDSHAKE_TIMEOUT_SECONDS, BROWSER_START_GRACE_SECONDS
from web_llm_bridge.transport.extension import ExtensionTransport


class BrowserLauncherTests(unittest.TestCase):
    @patch("web_llm_bridge.browser.launcher.subprocess.Popen")
    def test_launch_does_not_add_profile_arguments(self, popen):
        launcher = BrowserLauncher("browser.exe")
        launcher.launch("https://example.test")
        self.assertEqual(popen.call_args.args[0], ["browser.exe", "https://example.test"])

    def test_missing_executable_is_structured(self):
        with patch("web_llm_bridge.browser.launcher._default_executable", return_value=None):
            with self.assertRaises(BrowserLaunchError) as caught:
                BrowserLauncher().launch()
        self.assertEqual(caught.exception.code, "BROWSER_NOT_FOUND")


class BrowserBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_starts_then_waits(self):
        transport = AsyncMock()
        transport.connected = False
        launcher = MagicMock()
        bootstrap = BrowserBootstrap(transport, launcher)
        with patch("web_llm_bridge.browser.launcher.BROWSER_GRACE_SECONDS", 0):
            await bootstrap.start("https://example.test", handshake_timeout=1)
        transport.start.assert_awaited_once()
        launcher.launch.assert_called_once_with("https://example.test")
        transport.wait_until_ready.assert_awaited_once_with(1)


class ExtensionReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_until_ready_timeout_has_stable_code(self):
        transport = ExtensionTransport()
        with self.assertRaises(RPCError) as caught:
            await transport.wait_until_ready(0)
        self.assertEqual(caught.exception.code, "EXTENSION_HANDSHAKE_TIMEOUT")

    async def test_ready_event_reports_connected(self):
        transport = ExtensionTransport()
        transport._client = object()
        transport._ready.set()
        await transport.wait_until_ready(0)
        self.assertTrue(transport.connected)


class BrowserProtocolConstantTests(unittest.TestCase):
    def test_startup_windows_are_public(self):
        self.assertEqual(BROWSER_START_GRACE_SECONDS, 2.0)
        self.assertEqual(BROWSER_HANDSHAKE_TIMEOUT_SECONDS, 60.0)
