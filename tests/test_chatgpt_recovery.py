import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pro_bridge.chatgpt import ChatGPTDriver


class ChatGPTRecoveryTests(unittest.TestCase):
    def test_ensure_recovers_once_after_cdp_race(self):
        async def run():
            driver = ChatGPTDriver()
            browser = SimpleNamespace(is_connected=lambda: True)
            connect = AsyncMock(
                side_effect=[RuntimeError("CDP disappeared"), browser]
            )
            driver._pw = SimpleNamespace(
                chromium=SimpleNamespace(connect_over_cdp=connect)
            )

            with patch("pro_bridge.chatgpt.config.AUTO_START_BROWSER", True), patch(
                "pro_bridge.chatgpt.config.CDP_URL", "http://127.0.0.1:9222"
            ), patch(
                "pro_bridge.chatgpt.config.BROWSER_START_TIMEOUT", 20.0
            ), patch(
                "pro_bridge.chatgpt.config.BROWSER_START_COMMAND", ""
            ), patch(
                "pro_bridge.chatgpt.launch_local_browser",
                new=AsyncMock(return_value=True),
            ) as launch:
                await driver._ensure()

            self.assertIs(driver._browser, browser)
            self.assertEqual(connect.await_count, 2)
            launch.assert_awaited_once_with(
                "http://127.0.0.1:9222",
                timeout=20.0,
                custom_command=None,
            )

        asyncio.run(run())

    def test_ensure_does_not_recover_when_auto_start_disabled(self):
        async def run():
            driver = ChatGPTDriver()
            connect = AsyncMock(side_effect=RuntimeError("CDP unavailable"))
            driver._pw = SimpleNamespace(
                chromium=SimpleNamespace(connect_over_cdp=connect)
            )

            with patch("pro_bridge.chatgpt.config.AUTO_START_BROWSER", False), patch(
                "pro_bridge.chatgpt.config.CDP_URL", "http://127.0.0.1:9222"
            ), patch(
                "pro_bridge.chatgpt.launch_local_browser",
                new_callable=AsyncMock,
            ) as launch:
                with self.assertRaisesRegex(RuntimeError, "CDP unavailable"):
                    await driver._ensure()

            self.assertEqual(connect.await_count, 1)
            launch.assert_not_awaited()

        asyncio.run(run())

    def test_ensure_does_not_retry_remote_cdp(self):
        async def run():
            driver = ChatGPTDriver()
            connect = AsyncMock(side_effect=RuntimeError("remote CDP failed"))
            driver._pw = SimpleNamespace(
                chromium=SimpleNamespace(connect_over_cdp=connect)
            )

            with patch("pro_bridge.chatgpt.config.AUTO_START_BROWSER", True), patch(
                "pro_bridge.chatgpt.config.CDP_URL", "http://192.168.1.20:9222"
            ), patch(
                "pro_bridge.chatgpt.config.BROWSER_START_TIMEOUT", 20.0
            ), patch(
                "pro_bridge.chatgpt.config.BROWSER_START_COMMAND", ""
            ), patch(
                "pro_bridge.chatgpt.launch_local_browser",
                new=AsyncMock(return_value=False),
            ) as launch:
                with self.assertRaisesRegex(RuntimeError, "remote CDP failed"):
                    await driver._ensure()

            self.assertEqual(connect.await_count, 1)
            launch.assert_awaited_once_with(
                "http://192.168.1.20:9222",
                timeout=20.0,
                custom_command=None,
            )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
