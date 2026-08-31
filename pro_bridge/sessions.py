"""Persistent mapping between caller session names and ChatGPT conversations."""
import json
import os
import tempfile


class SessionStore:
    """Small JSON-backed session -> conversation_id registry.

    The file is deliberately human-readable and atomically replaced on writes so
    a bridge/process crash cannot leave a half-written registry behind.
    """

    def __init__(self, path: str):
        self.path = os.path.expanduser(path)
        self._sessions = self._load()

    @staticmethod
    def _normalize(session: str) -> str:
        if not isinstance(session, str):
            raise ValueError("session must be a string")
        value = session.strip()
        if not value:
            raise ValueError("session must not be empty")
        if len(value) > 200:
            raise ValueError("session must be 200 characters or fewer")
        return value

    def _load(self) -> dict[str, str]:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            # Keep the bridge usable even if an old/manual file is malformed.
            # A later successful write will replace it with valid JSON.
            return {}

        if not isinstance(data, dict):
            return {}

        result = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, str) and key and value:
                result[key] = value
        return result

    def _save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".sessions-",
            suffix=".json.tmp",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    self._sessions,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass

    def get(self, session: str) -> str | None:
        return self._sessions.get(self._normalize(session))

    def set(self, session: str, conversation_id: str) -> None:
        key = self._normalize(session)
        if not conversation_id or not isinstance(conversation_id, str):
            raise ValueError("conversation_id must not be empty")
        self._sessions[key] = conversation_id
        self._save()

    def reset(self, session: str) -> str | None:
        key = self._normalize(session)
        previous = self._sessions.pop(key, None)
        if previous is not None:
            self._save()
        return previous

    def snapshot(self) -> dict[str, str]:
        return dict(self._sessions)
