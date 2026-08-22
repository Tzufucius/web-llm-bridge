import json
import tempfile
import unittest
from pathlib import Path

from tools.chatgpt_web_bridge.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_create_update_and_sorted_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            first = store.create("first", 1, "https://chatgpt.com/c/first")
            second = store.create("second", 2, "https://chatgpt.com/c/second")
            self.assertFalse(store.get(first["session_id"])["active"])
            self.assertTrue(store.get(second["session_id"])["active"])

            store.update("first", active=True, sequence=8)
            records = store.list()
            self.assertEqual(records[0]["session_id"], "first")
            self.assertEqual(records[0]["sequence"], 8)
            self.assertTrue(Path(directory, "index.json").exists())
            self.assertTrue(Path(directory, "first.json").exists())

    def test_corrupt_index_and_record_do_not_block_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            store.create("valid", 1, "https://chatgpt.com/c/valid")
            Path(directory, "index.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(store.get("valid")["session_id"], "valid")

            Path(directory, "valid.json").write_text("{broken", encoding="utf-8")
            self.assertIsNone(store.get("valid"))

    def test_upsert_uses_atomic_json_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            store.upsert(
                {
                    "session_id": "atomic",
                    "tab_id": 9,
                    "current_url": "https://chatgpt.com/c/atomic",
                    "sequence": 4,
                    "active": True,
                }
            )
            data = json.loads(Path(directory, "atomic.json").read_text(encoding="utf-8"))
            self.assertEqual(data["sequence"], 4)
            self.assertFalse(any(Path(directory).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
