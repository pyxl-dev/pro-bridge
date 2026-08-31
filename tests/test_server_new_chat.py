import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pro_bridge import server


class _FakeSessions:
    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})
        self.reset_calls = []

    def get(self, session):
        return self.mapping.get(session)

    def reset(self, session):
        self.reset_calls.append(session)
        return self.mapping.pop(session, None)


class NewChatTransactionTests(unittest.TestCase):
    def test_failure_preserves_previous_mapping(self):
        async def run():
            sessions = _FakeSessions({"developer": "conv-old"})
            driver = SimpleNamespace(
                new_chat=AsyncMock(side_effect=RuntimeError("navigation failed"))
            )

            with (
                patch.object(server, "_sessions", sessions),
                patch.object(server, "_driver", driver),
                patch.object(server, "_session_lock", asyncio.Lock()),
            ):
                with self.assertRaisesRegex(RuntimeError, "navigation failed"):
                    await server._new_chat_for_session("developer", "header")

            self.assertEqual(sessions.mapping["developer"], "conv-old")
            self.assertEqual(sessions.reset_calls, [])
            driver.new_chat.assert_awaited_once_with()

        asyncio.run(run())

    def test_success_resets_mapping_after_browser_operation(self):
        async def run():
            sessions = _FakeSessions({"developer": "conv-old"})

            async def new_chat():
                # The old mapping must still exist while the browser operation
                # is executing; reset happens only after this returns.
                self.assertEqual(sessions.mapping["developer"], "conv-old")
                self.assertEqual(sessions.reset_calls, [])
                return {
                    "url": "https://chatgpt.com/",
                    "conversation_id": None,
                }

            driver = SimpleNamespace(new_chat=AsyncMock(side_effect=new_chat))

            with (
                patch.object(server, "_sessions", sessions),
                patch.object(server, "_driver", driver),
                patch.object(server, "_session_lock", asyncio.Lock()),
            ):
                result = await server._new_chat_for_session("developer", "header")

            self.assertNotIn("developer", sessions.mapping)
            self.assertEqual(sessions.reset_calls, ["developer"])
            self.assertEqual(result["previous_conversation_id"], "conv-old")
            self.assertEqual(result["session"], "developer")
            self.assertEqual(result["session_source"], "header")
            self.assertTrue(result["reset"])

        asyncio.run(run())

    def test_stateless_new_chat_does_not_touch_session_store(self):
        async def run():
            sessions = _FakeSessions({"developer": "conv-old"})
            driver = SimpleNamespace(
                new_chat=AsyncMock(
                    return_value={
                        "url": "https://chatgpt.com/",
                        "conversation_id": None,
                    }
                )
            )

            with (
                patch.object(server, "_sessions", sessions),
                patch.object(server, "_driver", driver),
                patch.object(server, "_session_lock", asyncio.Lock()),
            ):
                result = await server._new_chat_for_session(None, "none")

            self.assertEqual(sessions.mapping, {"developer": "conv-old"})
            self.assertEqual(sessions.reset_calls, [])
            self.assertIsNone(result["previous_conversation_id"])
            self.assertFalse(result["reset"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
