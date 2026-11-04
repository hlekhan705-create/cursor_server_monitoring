import os
import sqlite3
import tempfile
import unittest

from werkzeug.security import check_password_hash


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self.tmpdir.name, "monitor.db")
        os.environ["SECRET_KEY"] = "test-secret"
        import importlib

        import app as app_module

        importlib.reload(app_module)
        self.app_module = app_module
        self.client = app_module.app.test_client()
        self.client.application.config["REMOTE_READER"] = (
            lambda *args, **kwargs: self.app_module.empty_reading()
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_password_is_stored_as_a_hash(self):
        with sqlite3.connect(os.environ["DATABASE_PATH"]) as conn:
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()[0]
        self.assertNotEqual(stored, "admin")
        self.assertTrue(stored.startswith("pbkdf2:sha256"))
        self.assertTrue(check_password_hash(stored, "admin"))

    def test_seed_does_not_replace_an_existing_hash(self):
        with sqlite3.connect(os.environ["DATABASE_PATH"]) as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                ("pbkdf2:sha256:kept", "admin"),
            )
        self.app_module.init_db(os.environ["DATABASE_PATH"])
        with sqlite3.connect(os.environ["DATABASE_PATH"]) as conn:
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()[0]
        self.assertEqual(stored, "pbkdf2:sha256:kept")

    def test_correct_password_opens_servers(self):
        response = self.client.post(
            "/",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/servers"))
        page = self.client.get("/servers")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"This server", page.data)

    def test_wrong_password_stays_on_sign_in(self):
        response = self.client.post(
            "/",
            data={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password.", response.data)
        self.assertNotIn(b"This server", response.data)

    def test_servers_and_metrics_require_sign_in(self):
        for path in ("/servers", "/metrics"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["Location"].endswith("/"))

    def test_sign_out_closes_servers(self):
        self.client.post("/", data={"username": "admin", "password": "admin"})
        self.client.post("/sign-out")
        response = self.client.get("/servers", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))

    def test_sign_in_page_matches_the_lab_layout(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Server monitoring", html)
        self.assertIn(">Sign in<", html)
        self.assertIn(">Servers<", html)
        self.assertIn(">Metrics<", html)
        self.assertIn("One shared admin account for this local demo.", html)
        self.assertNotIn("Sign-in is not active yet.", html)
        self.assertNotIn("Dashboard", html)
        self.assertNotIn("Add server", html)
        self.assertNotIn(">History<", html)


if __name__ == "__main__":
    unittest.main()
