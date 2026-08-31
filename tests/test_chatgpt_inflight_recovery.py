import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from pro_bridge.chatgpt import ChatGPTDriver


CONV = "6a957be8-41f4-83eb-9231-dc8fe6c67dd9"
DRIVER_ERROR = RuntimeError("Connection closed while reading from the driver")


class _CountLocator:
    def __init__(self, value=0):
        self._value = value

    async def count(self):
        return self._value


class _Page:
    def __init__(self, *, url, count=0):
        self.url = url
        self._locator = _CountLocator(count)
        self.listeners = []

    def locator(self, _selector):
        return self._locator

    def on(self, event, callback):
        self.listeners.append((event, callback))

    def remove_listener(self, event, callback):
        try:
            self.listeners.remove((event, callback))
        except ValueError:
            pass


class InflightRecoveryTests(unittest.TestCase):
    def test_wait_for_answer_recovers_driver_once_and_returns_existing_reply(self):
        async def run():
            driver = ChatGPTDriver()
            first_page = _Page(url=f"https://chatgpt.com/c/{CONV}")
            recovered_page = _Page(url=f"https://chatgpt.com/c/{CONV}")
            complete = {
                "index": 0,
                "text": "DONE",
                "model": "gpt-test",
                "copyVisible": True,
                "stopVisible": False,
                "turnId": "conversation-turn-1",
            }

            with patch.object(
                driver,
                "_recover_inflight_page",
                new=AsyncMock(return_value=(recovered_page, CONV)),
            ) as recover, patch.object(
                driver,
                "_assistant_snapshot",
                new=AsyncMock(side_effect=[DRIVER_ERROR, complete]),
            ):
                page, text, conv = await driver._wait_for_answer(
                    first_page,
                    0,
                    conversation_id=CONV,
                    deadline=time.monotonic() + 1,
                )

            self.assertIs(page, recovered_page)
            self.assertEqual(text, "DONE")
            self.assertEqual(conv, CONV)
            recover.assert_awaited_once_with(CONV)

        asyncio.run(run())

    def test_wait_for_answer_never_loops_driver_recovery(self):
        async def run():
            driver = ChatGPTDriver()
            first_page = _Page(url=f"https://chatgpt.com/c/{CONV}")
            recovered_page = _Page(url=f"https://chatgpt.com/c/{CONV}")

            with patch.object(
                driver,
                "_recover_inflight_page",
                new=AsyncMock(return_value=(recovered_page, CONV)),
            ) as recover, patch.object(
                driver,
                "_assistant_snapshot",
                new=AsyncMock(side_effect=[DRIVER_ERROR, DRIVER_ERROR]),
            ):
                with self.assertRaisesRegex(RuntimeError, "Connection closed"):
                    await driver._wait_for_answer(
                        first_page,
                        0,
                        conversation_id=CONV,
                        deadline=time.monotonic() + 1,
                    )

            self.assertEqual(recover.await_count, 1)

        asyncio.run(run())

    def test_wait_for_answer_does_not_mask_unrelated_playwright_error(self):
        async def run():
            driver = ChatGPTDriver()
            page = _Page(url=f"https://chatgpt.com/c/{CONV}")

            with patch.object(
                driver,
                "_recover_inflight_page",
                new_callable=AsyncMock,
            ) as recover, patch.object(
                driver,
                "_assistant_snapshot",
                new=AsyncMock(side_effect=RuntimeError("selector exploded")),
            ):
                with self.assertRaisesRegex(RuntimeError, "selector exploded"):
                    await driver._wait_for_answer(
                        page,
                        0,
                        conversation_id=CONV,
                        deadline=time.monotonic() + 1,
                    )

            recover.assert_not_awaited()

        asyncio.run(run())

    def test_wait_for_answer_ignores_previous_nonempty_turn_until_new_index(self):
        async def run():
            driver = ChatGPTDriver()
            page = _Page(url=f"https://chatgpt.com/c/{CONV}")
            previous = {
                "index": 3,
                "text": "PREVIOUS",
                "model": "gpt-old",
                "copyVisible": True,
                "stopVisible": False,
                "turnId": "conversation-turn-18",
            }
            current = {
                "index": 4,
                "text": "CURRENT",
                "model": "gpt-new",
                "copyVisible": True,
                "stopVisible": False,
                "turnId": "conversation-turn-20",
            }

            with patch.object(
                driver,
                "_assistant_snapshot",
                new=AsyncMock(side_effect=[previous, current]),
            ), patch(
                "pro_bridge.chatgpt.asyncio.sleep",
                new=AsyncMock(),
            ):
                _page, text, conv = await driver._wait_for_answer(
                    page,
                    4,
                    conversation_id=CONV,
                    deadline=time.monotonic() + 1,
                )

            self.assertEqual(text, "CURRENT")
            self.assertEqual(conv, CONV)

        asyncio.run(run())

    def test_ask_sends_prompt_exactly_once_when_waiter_returns_recovered_page(self):
        async def run():
            driver = ChatGPTDriver()
            page = _Page(url=f"https://chatgpt.com/c/{CONV}", count=4)
            recovered_page = _Page(url=f"https://chatgpt.com/c/{CONV}", count=5)

            with patch.object(
                driver,
                "_get_page",
                new=AsyncMock(return_value=page),
            ), patch.object(
                driver,
                "_send",
                new=AsyncMock(),
            ) as send, patch.object(
                driver,
                "_wait_for_answer",
                new=AsyncMock(return_value=(recovered_page, "FINAL", CONV)),
            ) as wait_for_answer, patch.object(
                driver,
                "_last_assistant_slug",
                new=AsyncMock(return_value="gpt-test"),
            ):
                result = await driver.ask("hello", conversation_id=CONV)

            send.assert_awaited_once_with(page, "hello")
            self.assertEqual(wait_for_answer.await_count, 1)
            self.assertEqual(result["text"], "FINAL")
            self.assertEqual(result["conversation_id"], CONV)
            self.assertEqual(result["model"], "gpt-test")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
