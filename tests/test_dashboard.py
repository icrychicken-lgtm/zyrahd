from __future__ import annotations

import unittest

from dashboard import create_dashboard
from database import init_database


class DashboardSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        cls.app = create_dashboard()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    def setUp(self) -> None:
        self.client = self.app.test_client()

    def login_as_admin(self) -> None:
        with self.client.session_transaction() as session:
            session["user"] = {
                "id": "1",
                "username": "Test Admin",
                "tag": "test-admin",
                "avatar": "",
                "roles": [],
                "guild_permissions": "8",
            }

    def test_login_page_renders(self) -> None:
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"zyrahd", response.data)

    def test_protected_page_redirects_to_login(self) -> None:
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_all_dashboard_pages_render_for_admin(self) -> None:
        self.login_as_admin()
        paths = (
            "/dashboard",
            "/tickets",
            "/settings",
            "/ticket-settings",
            "/security",
            "/moderation",
            "/embed-designer",
            "/team",
            "/dashboard-roles",
            "/audit-log",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_unprivileged_member_can_only_open_tickets(self) -> None:
        with self.client.session_transaction() as session:
            session["user"] = {
                "id": "2",
                "username": "Member",
                "tag": "member",
                "avatar": "",
                "roles": [],
                "guild_permissions": "0",
            }
        self.assertEqual(self.client.get("/tickets").status_code, 200)
        self.assertEqual(self.client.get("/settings").status_code, 403)
        self.assertEqual(self.client.get("/api/resources").status_code, 403)


if __name__ == "__main__":
    unittest.main()
