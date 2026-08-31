import unittest

from pro_bridge.identity import profile_from_context, resolve_session


class _Headers(dict):
    def get(self, key, default=None):
        # Starlette Headers is case-insensitive; emulate that behavior here.
        wanted = key.lower()
        for existing, value in self.items():
            if existing.lower() == wanted:
                return value
        return default


class _Request:
    def __init__(self, headers):
        self.headers = _Headers(headers)


class _RequestContext:
    def __init__(self, headers):
        self.request = _Request(headers)


class _Context:
    def __init__(self, headers):
        self.request_context = _RequestContext(headers)


class IdentityTests(unittest.TestCase):
    def test_reads_hermes_profile_header(self):
        ctx = _Context({"X-Hermes-Profile": "developer"})
        self.assertEqual(
            profile_from_context(ctx, "X-Hermes-Profile"),
            "developer",
        )

    def test_header_is_case_insensitive(self):
        ctx = _Context({"x-hermes-profile": "business"})
        self.assertEqual(
            profile_from_context(ctx, "X-Hermes-Profile"),
            "business",
        )

    def test_header_wins_over_explicit_session(self):
        ctx = _Context({"X-Hermes-Profile": "developer"})
        session, source = resolve_session(
            "wrong-session",
            ctx,
            "X-Hermes-Profile",
        )
        self.assertEqual(session, "developer")
        self.assertEqual(source, "header")

    def test_argument_is_fallback_without_header(self):
        ctx = _Context({})
        session, source = resolve_session(
            "research",
            ctx,
            "X-Hermes-Profile",
        )
        self.assertEqual(session, "research")
        self.assertEqual(source, "argument")

    def test_missing_identity_is_stateless(self):
        ctx = _Context({})
        session, source = resolve_session(None, ctx, "X-Hermes-Profile")
        self.assertIsNone(session)
        self.assertEqual(source, "none")

    def test_missing_request_context_is_safe(self):
        class Empty:
            pass

        self.assertIsNone(profile_from_context(Empty(), "X-Hermes-Profile"))


if __name__ == "__main__":
    unittest.main()
