import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from pro_bridge.browser_guard import (
    cdp_target,
    launch_local_browser,
    resolve_start_command,
)


class BrowserGuardTests(unittest.TestCase):
    def test_local_cdp_targets(self):
        self.assertEqual(cdp_target("http://localhost:9222"), ("localhost", 9222))
        self.assertEqual(cdp_target("http://127.0.0.1:9333"), ("127.0.0.1", 9333))
        self.assertEqual(cdp_target("https://localhost"), ("localhost", 443))

    def test_remote_cdp_is_never_auto_started(self):
        self.assertIsNone(cdp_target("http://192.168.1.10:9222"))
        self.assertIsNone(cdp_target("https://browser.example.com:9222"))

    def test_custom_command_is_split_without_shell(self):
        self.assertEqual(
            resolve_start_command('python launcher.py --mode "background hidden"'),
            ["python", "launcher.py", "--mode", "background hidden"],
        )

    def test_remote_launch_returns_false_without_spawning(self):
        async def run():
            with patch(
                "pro_bridge.browser_guard.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
            ) as spawn:
                result = await launch_local_browser("http://10.0.0.8:9222")
                self.assertFalse(result)
                spawn.assert_not_awaited()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
