from __future__ import annotations

import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.database import Database
from app.parser import parse_whatsapp_text
from app.providers import ProviderError, chat_completion, parse_json_response, redact_sensitive
from app.service import CreatorService


SAMPLE = """[2:31 PM, 6/23/2026] New Horizons: Hi Katlyn!\nJust following up.\n[2:33 PM, 6/23/2026] Katlyn: Hi! Yes, I'm interested.\n"""


class ParserTests(unittest.TestCase):
    def test_parses_multiline_and_senders(self) -> None:
        messages = parse_whatsapp_text(SAMPLE)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender, "New Horizons")
        self.assertIn("following up", messages[0].body)

    def test_duplicate_messages_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db")
            creator = db.create_creator({"name": "Katlyn"})
            messages = parse_whatsapp_text(SAMPLE)
            self.assertEqual(db.add_messages(creator["id"], messages, "New Horizons"), (2, 0))
            self.assertEqual(db.add_messages(creator["id"], messages, "New Horizons"), (0, 2))

    def test_visual_variants_are_skipped_without_merging_real_messages(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db")
            creator = db.create_creator({"name": "Katlyn"})
            original = parse_whatsapp_text(
                "[10:46 AM, 7/6/2026] Katlyn: Great 😊\n"
                "[10:46 AM, 7/6/2026] Katlyn: Different message\n"
            )
            visual_variant = parse_whatsapp_text("[10:46 AM, 7/6/2026] Katlyn: Great\n")
            self.assertEqual(db.add_messages(creator["id"], original, "New Horizons"), (2, 0))
            self.assertEqual(db.add_messages(creator["id"], visual_variant, "New Horizons"), (0, 1))
            self.assertEqual(len(db.list_messages(creator["id"])), 2)

    def test_batch_import_creates_matches_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db")
            service = CreatorService(db)
            payload = [{
                "name": "WhatsApp Chat with Katlyn.txt",
                "data": base64.b64encode(SAMPLE.replace("Katlyn:", "Katlyn付费100:").encode()).decode(),
            }]
            first = service.import_batch(payload)
            second = service.import_batch(payload)
            self.assertEqual(first["creators_created"], 1)
            self.assertEqual(first["messages_added"], 2)
            self.assertEqual(second["creators_created"], 0)
            self.assertEqual(second["messages_added"], 0)
            self.assertEqual(second["messages_skipped"], 2)

    def test_batch_import_reads_zip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db")
            service = CreatorService(db)
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, "w") as archive:
                archive.writestr("WhatsApp Chat with Katlyn.txt", SAMPLE)
                archive.writestr("IMG-001.jpg", b"ignored")
            result = service.import_batch([{
                "name": "Katlyn.zip",
                "data": base64.b64encode(memory.getvalue()).decode(),
            }])
            self.assertEqual(result["files"], 1)
            self.assertEqual(result["messages_added"], 2)
            self.assertEqual(result["api_calls"], 0)

    def test_visible_whatsapp_import_uses_same_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db")
            db.create_creator({"name": "Katlyn"})
            service = CreatorService(db)
            first = service.import_visible_whatsapp("katlyn付费100", SAMPLE)
            second = service.import_visible_whatsapp("katlyn付费100", SAMPLE)
            self.assertEqual(first["messages_added"], 2)
            self.assertEqual(second["messages_added"], 0)
            self.assertEqual(second["messages_skipped"], 2)
            self.assertEqual(first["api_calls"], 0)


class SafetyTests(unittest.TestCase):
    def test_redacts_remote_personal_data(self) -> None:
        text = "Email me at creator@example.com or +1 (310) 555-0188"
        redacted = redact_sensitive(text)
        self.assertNotIn("creator@example.com", redacted)
        self.assertNotIn("555-0188", redacted)

    def test_json_fence_is_accepted(self) -> None:
        self.assertEqual(parse_json_response('```json\n{"ok": true}\n```')["ok"], True)

    @patch("app.providers._chat_completion")
    def test_groq_rate_limit_uses_cloud_fallback_first(self, mocked_chat) -> None:
        mocked_chat.side_effect = [
            ProviderError("模型接口返回 429: rate limit", 429),
            ("{\"ok\": true}", "openai/gpt-oss-120b"),
        ]
        content, model = chat_completion(
            {
                "provider": "groq",
                "base_url": "https://api.groq.com/openai/v1",
                "model": "qwen/qwen3.6-27b",
                "api_key": "test",
                "fallback_local": True,
            },
            [{"role": "user", "content": "test"}],
        )
        self.assertIn('"ok": true', content)
        self.assertIn("openai/gpt-oss-120b", model)
        self.assertEqual(mocked_chat.call_args_list[1].args[0]["model"], "openai/gpt-oss-120b")

    @patch("app.providers._chat_completion")
    def test_auth_error_does_not_hide_problem_with_another_cloud_model(self, mocked_chat) -> None:
        mocked_chat.side_effect = [
            ProviderError("模型接口返回 401: invalid key", 401),
            ("local result", "gemma-4-12b"),
        ]
        _, model = chat_completion(
            {
                "provider": "groq",
                "model": "qwen/qwen3.6-27b",
                "api_key": "bad",
                "fallback_local": True,
            },
            [{"role": "user", "content": "test"}],
        )
        self.assertIn("已转本机", model)
        self.assertEqual(mocked_chat.call_count, 2)
        self.assertEqual(mocked_chat.call_args_list[1].args[0]["provider"], "local")


if __name__ == "__main__":
    unittest.main()
