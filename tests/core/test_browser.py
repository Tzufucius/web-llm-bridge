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

    def test_default_browser_failure_is_structured(self):
        with patch("web_llm_bridge.browser.launcher.webbrowser.open", return_value=False):
            with self.assertRaises(BrowserLaunchError) as caught:
                BrowserLauncher().launch()
        self.assertEqual(caught.exception.code, "BROWSER_LAUNCH_FAILED")


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

    async def test_concurrent_starts_launch_once(self):
        class FakeTransport:
            def __init__(self):
                self.connected = False
                self.ready = asyncio.Event()

            async def start(self):
                return None

            async def wait_until_ready(self, _timeout):
                await self.ready.wait()

        transport = FakeTransport()
        launcher = MagicMock()
        def launch(_url):
            transport.connected = True
            transport.ready.set()
        launcher.launch.side_effect = launch
        bootstrap = BrowserBootstrap(transport, launcher)
        with patch("web_llm_bridge.browser.launcher.BROWSER_GRACE_SECONDS", 0):
            await asyncio.gather(*(bootstrap.start("about:blank", handshake_timeout=1) for _ in range(5)))
        launcher.launch.assert_called_once_with("about:blank")


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
