import json
import os
import sqlite3
import tempfile
import unittest


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "monitor.db")
        os.environ["DATABASE_PATH"] = self.db_path
        os.environ["SECRET_KEY"] = "test-secret"
        os.environ.pop("SERVERS_PATH", None)
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

    def sign_in(self):
        return self.client.post(
            "/",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )

    def test_valid_config_reloads_server_rows(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO servers (name, host) VALUES (?, ?)",
                ("Extra", "other-host"),
            )
        path = os.path.join(self.tmpdir.name, "servers.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"name": "This server", "host": "localhost"}], handle)
        servers = self.app_module.load_servers(path)
        self.app_module.replace_servers(self.db_path, servers)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT name, host FROM servers ORDER BY id").fetchall()
        self.assertEqual(rows, [("This server", "localhost")])

    def test_empty_config_stops_startup(self):
        path = os.path.join(self.tmpdir.name, "empty.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(" \n")
        with self.assertRaises(self.app_module.ConfigError) as raised:
            self.app_module.load_servers(path)
        self.assertIn("empty", str(raised.exception))

    def test_invalid_json_stops_startup(self):
        path = os.path.join(self.tmpdir.name, "bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{")
        with self.assertRaises(self.app_module.ConfigError) as raised:
            self.app_module.load_servers(path)
        self.assertIn("not valid JSON", str(raised.exception))

    def test_server_page_shows_the_lab_table(self):
        self.sign_in()
        self.client.application.config["HOST_READER"] = lambda: {
            "online": True,
            "cpu": 12.5,
            "memory": 40.0,
            "disk": 55.0,
            "mount": "/",
        }
        page = self.client.get("/servers")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Monitored Linux servers", html)
        self.assertIn("Current readings refresh every 15 seconds", html)
        self.assertIn("This server", html)
        self.assertIn("localhost", html)
        self.assertIn("online", html)
        self.assertIn("12.5%", html)
        self.assertIn("40.0%", html)
        self.assertIn("55.0%", html)
        self.assertIn("Add server", html)
        self.assertIn("Remove", html)
        self.assertIn("/cpu", html)
        self.assertIn('content="15"', html)
        self.assertNotIn(">Delete<", html)
        self.assertNotIn("<h1>CPU</h1>", html)

    def test_add_and_remove_server(self):
        path = os.path.join(self.tmpdir.name, "servers.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"name": "This server", "host": "localhost"}], handle)
        self.client.application.config["SERVERS_PATH"] = path
        self.client.application.config["HOST_READER"] = lambda: {
            "online": True,
            "cpu": 1.0,
            "memory": 2.0,
            "disk": 3.0,
            "mount": "/",
        }
        self.app_module.replace_servers(
            self.db_path, self.app_module.load_servers(path)
        )
        self.sign_in()
        added = self.client.post(
            "/servers",
            data={"name": "Lab host", "host": "lab.example"},
            follow_redirects=True,
        )
        self.assertIn("Lab host", added.get_data(as_text=True))
        with sqlite3.connect(self.db_path) as conn:
            server_id = conn.execute(
                "SELECT id FROM servers WHERE name = ?",
                ("Lab host",),
            ).fetchone()[0]
        removed = self.client.post(
            f"/servers/{server_id}/remove",
            follow_redirects=True,
        )
        self.assertNotIn("Lab host", removed.get_data(as_text=True))
        listed = [
            (item["name"], item["host"])
            for item in self.app_module.load_servers(path)
        ]
        self.assertNotIn(("Lab host", "lab.example"), listed)

    def test_cpu_success_and_failure_leave_the_database_unchanged(self):
        calls = []

        def fake(interval=None, percpu=False):
            calls.append((interval, percpu))
            if percpu:
                return [10.0, 30.0]
            return 20.0

        sample = self.app_module.read_cpu(fake)
        self.assertEqual(calls, [(1, False), (1, True)])
        self.assertEqual(sample["overall"], 20.0)
        self.assertEqual(sample["cores"], [10.0, 30.0])

        before = self.app_module.snapshot_db(self.db_path)

        def fail(interval=None, percpu=False):
            raise RuntimeError("sensor")

        self.assertIsNone(self.app_module.read_cpu(fail))
        self.sign_in()
        self.client.application.config["CPU_READER"] = fail
        page = self.client.get("/metrics")
        self.assertIn(b"CPU reading failed.", page.data)
        self.assertEqual(self.app_module.snapshot_db(self.db_path), before)

    def test_cpu_page_renders_sample_and_refreshes(self):
        def fake(interval=None, percpu=False):
            if percpu:
                return [5.0, 15.0]
            return 10.0

        self.sign_in()
        self.client.application.config["CPU_READER"] = fake
        server_id = self.app_module.list_servers(self.db_path)[0]["id"]
        page = self.client.get(f"/servers/{server_id}/cpu")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("10.0%", html)
        self.assertIn("Core 1", html)
        self.assertIn("Core 2", html)
        self.assertIn('http-equiv="refresh" content="5"', html)
        self.assertNotIn("<form", html.split("</nav>", 1)[-1])

    def test_remote_server_shows_its_own_readings(self):
        path = os.path.join(self.tmpdir.name, "servers.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {"name": "This server", "host": "localhost"},
                    {
                        "name": "Monitoring_server",
                        "host": "20.235.34.15",
                        "port": 22,
                        "username": "lekhanh",
                    },
                ],
                handle,
            )
        self.client.application.config["SERVERS_PATH"] = path
        self.app_module.replace_servers(
            self.db_path, self.app_module.load_servers(path)
        )
        self.client.application.config["HOST_READER"] = lambda: {
            "online": True,
            "cpu": 1.0,
            "memory": 2.0,
            "disk": 3.0,
            "mount": "/",
        }
        self.client.application.config["REMOTE_READER"] = (
            lambda host, port, username, identity: {
                "online": True,
                "cpu": 21.5,
                "memory": 47.0,
                "disk": 40.0,
                "mount": "/",
            }
        )
        self.sign_in()
        html = self.client.get("/servers").get_data(as_text=True)
        self.assertIn("Monitoring_server", html)
        self.assertIn("20.235.34.15:22", html)
        self.assertIn("21.5%", html)
        self.assertIn("47.0%", html)
        self.assertIn("1.0%", html)
        self.assertNotIn("ssh", html.lower())

    def test_remote_metric_text_parses(self):
        reading = self.app_module.parse_remote_metrics(
            "cpu 21.5\nmem 47.0\ndisk 40.0 /\n"
        )
        self.assertEqual(reading["cpu"], 21.5)
        self.assertEqual(reading["memory"], 47.0)
        self.assertEqual(reading["disk"], 40.0)
        self.assertEqual(reading["mount"], "/")

    def test_cpu_page_requires_sign_in(self):
        response = self.client.get("/servers/1/cpu", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))

    def test_restart_keeps_the_admin_hash_and_reloads_servers(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                ("pbkdf2:sha256:kept", "admin"),
            )
            conn.execute(
                "INSERT INTO servers (name, host) VALUES (?, ?)",
                ("Extra", "other-host"),
            )
        import importlib

        importlib.reload(self.app_module)
        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()[0]
            names = [
                row[0]
                for row in conn.execute("SELECT name FROM servers ORDER BY id")
            ]
        self.assertEqual(stored, "pbkdf2:sha256:kept")
        expected = [
            item["name"]
            for item in self.app_module.load_servers(
                self.app_module.app.config["SERVERS_PATH"]
            )
        ]
        self.assertEqual(names, expected)
        self.assertNotIn("Extra", names)


if __name__ == "__main__":
    unittest.main()
