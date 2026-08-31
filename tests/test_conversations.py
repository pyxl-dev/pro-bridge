import unittest

from pro_bridge.conversations import (
    conversation_id_from_url,
    normalize_conversation_id,
    resolve_conversation_reference,
)


CID = "6a95826b-1cc0-83eb-88a0-59aa0a0bec60"
OTHER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class ConversationReferenceTests(unittest.TestCase):
    def test_parse_chatgpt_url(self):
        self.assertEqual(
            conversation_id_from_url(f"https://chatgpt.com/c/{CID}"),
            CID,
        )

    def test_parse_legacy_host_and_query(self):
        self.assertEqual(
            conversation_id_from_url(f"https://chat.openai.com/c/{CID}?foo=bar"),
            CID,
        )

    def test_reject_share_url(self):
        with self.assertRaises(ValueError):
            conversation_id_from_url(f"https://chatgpt.com/share/{CID}")

    def test_reject_wrong_host(self):
        with self.assertRaises(ValueError):
            conversation_id_from_url(f"https://example.com/c/{CID}")

    def test_reject_invalid_uuid(self):
        with self.assertRaises(ValueError):
            normalize_conversation_id("not-an-id")

    def test_url_wins_as_explicit_reference(self):
        resolved, source = resolve_conversation_reference(
            None, f"https://chatgpt.com/c/{CID}"
        )
        self.assertEqual(resolved, CID)
        self.assertEqual(source, "url")

    def test_matching_id_and_url_allowed(self):
        resolved, source = resolve_conversation_reference(
            CID, f"https://chatgpt.com/c/{CID}"
        )
        self.assertEqual(resolved, CID)
        self.assertEqual(source, "url")

    def test_mismatched_id_and_url_rejected(self):
        with self.assertRaises(ValueError):
            resolve_conversation_reference(
                OTHER, f"https://chatgpt.com/c/{CID}"
            )


if __name__ == "__main__":
    unittest.main()
