import json
import os
import tempfile
import unittest
from pathlib import Path

from web_llm_bridge.session.store import SessionStore


class StoreTests(unittest.TestCase):
    def test_default_path_uses_home_sessions_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("WEB_LLM_BRIDGE_HOME")
            os.environ["WEB_LLM_BRIDGE_HOME"] = directory
            try:
                self.assertEqual(SessionStore().root_dir, Path(directory) / "sessions")
            finally:
                if previous is None:
                    os.environ.pop("WEB_LLM_BRIDGE_HOME", None)
                else:
                    os.environ["WEB_LLM_BRIDGE_HOME"] = previous

    def test_default_home_can_be_overridden_and_provider_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            saved = store.create("one", 1, "https://chatgpt.com/c/one", provider="chatgpt")
            self.assertEqual(saved["provider"], "chatgpt")
            self.assertEqual(store.get("one")["session_id"], "one")

    def test_v1_record_is_migrated_with_chatgpt_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "old.json").write_text(json.dumps({"version": 1, "session_id": "old", "tab_id": 7, "current_url": "https://chatgpt.com/c/old", "active": True}), encoding="utf-8")
            record = SessionStore(directory).get("old")
            self.assertEqual(record["provider"], "chatgpt")

    def test_invalid_record_fields_do_not_block_other_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "broken.json").write_text(
                json.dumps(
                    {
                        "session_id": "broken",
                        "tab_id": 3,
                        "current_url": "https://chatgpt.com/c/broken",
                        "sequence": "not-an-int",
                    }
                ),
                encoding="utf-8",
            )
            Path(directory, "valid.json").write_text(
                json.dumps(
                    {
                        "session_id": "valid",
                        "tab_id": 4,
                        "current_url": "https://chatgpt.com/c/valid",
                        "sequence": 2,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                [record["session_id"] for record in SessionStore(directory).list()],
                ["valid"],
            )

    def test_unsafe_id_and_invalid_timestamp_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid_records = [
                {
                    "session_id": "../poison",
                    "tab_id": 1,
                    "current_url": "https://chatgpt.com/c/poison",
                },
                {
                    "session_id": "bad-time",
                    "tab_id": 2,
                    "current_url": "https://chatgpt.com/c/time",
                    "updated_at": 0,
                },
                {
                    "session_id": "bad:record",
                    "tab_id": 3,
                    "current_url": "https://chatgpt.com/c/colon",
                },
                {
                    "session_id": "CON.json",
                    "tab_id": 4,
                    "current_url": "https://chatgpt.com/c/reserved",
                },
            ]
            Path(directory, "index.json").write_text(
                json.dumps({"sessions": invalid_records}), encoding="utf-8"
            )
            store = SessionStore(directory)
            self.assertEqual(store.list(), [])
            self.assertEqual(
                store.create("valid", 5, "https://chatgpt.com/c/valid")["session_id"],
                "valid",
            )

    def test_active_session_is_scoped_to_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(sessions_dir=directory)
            store.create("first", 1, "https://chatgpt.com/c/first", provider="chatgpt")
            store.create("second", 2, "https://second.example/c/second", provider="second")
            self.assertTrue(store.get("first")["active"])
            self.assertTrue(store.get("second")["active"])
