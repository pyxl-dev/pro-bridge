import json
import os
import tempfile
import unittest

from pro_bridge.sessions import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_set_get_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sessions.json")
            store = SessionStore(path)
            self.assertIsNone(store.get("developer"))

            store.set("developer", "conv-a")
            self.assertEqual(store.get("developer"), "conv-a")

            reloaded = SessionStore(path)
            self.assertEqual(reloaded.get("developer"), "conv-a")

    def test_sessions_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sessions.json")
            store = SessionStore(path)
            store.set("developer", "conv-a")
            store.set("business", "conv-b")

            self.assertEqual(store.get("developer"), "conv-a")
            self.assertEqual(store.get("business"), "conv-b")

    def test_reset_only_removes_requested_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sessions.json")
            store = SessionStore(path)
            store.set("developer", "conv-a")
            store.set("business", "conv-b")

            previous = store.reset("developer")
            self.assertEqual(previous, "conv-a")
            self.assertIsNone(store.get("developer"))
            self.assertEqual(store.get("business"), "conv-b")

            reloaded = SessionStore(path)
            self.assertIsNone(reloaded.get("developer"))
            self.assertEqual(reloaded.get("business"), "conv-b")

    def test_file_is_human_readable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sessions.json")
            store = SessionStore(path)
            store.set("developer", "conv-a")

            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data, {"developer": "conv-a"})

    def test_blank_session_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(os.path.join(tmp, "sessions.json"))
            with self.assertRaises(ValueError):
                store.get("   ")


if __name__ == "__main__":
    unittest.main()
