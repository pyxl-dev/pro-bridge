import asyncio
import unittest

from pro_bridge.chatgpt import ChatGPTDriver


class _DOMPage:
    """Mock page that simulates ChatGPT assistant nodes for page.evaluate()."""

    def __init__(self, nodes):
        self.nodes = nodes

    async def evaluate(self, script):
        # Guard the intended implementation shape: selection must walk assistant
        # nodes backwards and skip empty nodes before returning a snapshot.
        self.assertions = {
            "reverse": "assistants.length - 1" in script and "continue;" in script,
            "markdown": "querySelectorAll('.markdown')" in script,
            "same_turn": "copy-turn-action-button" in script,
        }

        for index in range(len(self.nodes) - 1, -1, -1):
            node = self.nodes[index]
            markdown = (node.get("markdown") or "").strip()
            text = markdown or (node.get("text") or "").strip()
            if not text:
                continue
            return {
                "index": index,
                "text": text,
                "model": node.get("model"),
                "copyVisible": bool(node.get("copyVisible")),
                "stopVisible": bool(node.get("stopVisible")),
                "turnId": node.get("turnId"),
            }
        return None


class AssistantDOMSelectionTests(unittest.TestCase):
    def test_empty_trailing_assistant_does_not_hide_completed_reply(self):
        async def run():
            driver = ChatGPTDriver()
            page = _DOMPage(
                [
                    {
                        "text": "older answer",
                        "model": "gpt-old",
                        "copyVisible": True,
                        "turnId": "conversation-turn-18",
                    },
                    {
                        "markdown": "Complete answer from turn 20",
                        "text": "wrapper text that must not win over markdown",
                        "model": "gpt-5-6-thinking",
                        "copyVisible": True,
                        "stopVisible": False,
                        "turnId": "conversation-turn-20",
                    },
                    {
                        "text": "   ",
                        "model": "wrong-empty-node-model",
                        "copyVisible": False,
                        "stopVisible": False,
                        "turnId": "conversation-turn-20",
                    },
                ]
            )

            snapshot = await driver._assistant_snapshot(page)
            text = await driver._extract_answer(page)
            slug = await driver._last_assistant_slug(page)
            state = await driver._completion_state(page)

            self.assertTrue(all(page.assertions.values()))
            self.assertEqual(snapshot["index"], 1)
            self.assertEqual(snapshot["turnId"], "conversation-turn-20")
            self.assertEqual(text, "Complete answer from turn 20")
            self.assertEqual(slug, "gpt-5-6-thinking")
            self.assertEqual(
                state,
                {"copyVisible": True, "stopVisible": False},
            )

        asyncio.run(run())

    def test_no_nonempty_assistant_is_not_a_completed_answer(self):
        async def run():
            driver = ChatGPTDriver()
            page = _DOMPage(
                [
                    {"text": ""},
                    {"text": "   ", "markdown": "\n"},
                ]
            )

            self.assertIsNone(await driver._assistant_snapshot(page))
            with self.assertRaisesRegex(RuntimeError, "No non-empty"):
                await driver._extract_answer(page)
            self.assertIsNone(await driver._last_assistant_slug(page))
            self.assertEqual(
                await driver._completion_state(page),
                {"copyVisible": False, "stopVisible": False},
            )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
