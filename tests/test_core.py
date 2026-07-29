from __future__ import annotations

import unittest

from bot.cogs.security import normalized
from bot.utils.tickets import _validate_answers
from dashboard import create_app
from database.models import JsonMixin


class CoreTests(unittest.TestCase):
    def test_word_filter_normalizes_simple_bypasses(self) -> None:
        self.assertEqual(normalized("B ö-S_E!"), "böse")
        self.assertIn(normalized("verboten"), normalized("v e r b o t e n"))

    def test_ticket_form_validation(self) -> None:
        fields = [
            {
                "id": "topic",
                "label": "Thema",
                "required": True,
                "min_length": 3,
                "max_length": 10,
            }
        ]
        self.assertEqual(_validate_answers(fields, {"topic": " Hilfe "}), {"topic": "Hilfe"})
        with self.assertRaisesRegex(ValueError, "Pflichtfeld"):
            _validate_answers(fields, {})
        with self.assertRaisesRegex(ValueError, "zu lang"):
            _validate_answers(fields, {"topic": "x" * 11})

    def test_json_mixin_has_safe_fallback(self) -> None:
        self.assertEqual(JsonMixin.decode('{"ok":true}', {}), {"ok": True})
        self.assertEqual(JsonMixin.decode("not-json", {}), {})

    def test_public_health_and_security_headers(self) -> None:
        app = create_app(testing=True)
        with app.test_client() as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["service"], "zyrahd.net")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_dashboard_requires_login(self) -> None:
        app = create_app(testing=True)
        with app.test_client() as client:
            response = client.get("/dashboard")
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
