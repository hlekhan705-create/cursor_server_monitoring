import json
import os
import sqlite3
import sys
from functools import wraps

import psutil
from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

DEMO_USERNAME = "admin"
DEMO_PASSWORD = "admin"
HASH_METHOD = "pbkdf2:sha256"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class ConfigError(Exception):
    pass


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "demo-local-secret")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["DATABASE_PATH"] = os.environ.get(
        "DATABASE_PATH", os.path.join(BASE_DIR, "data", "monitor.db")
    )
    app.config["SERVERS_PATH"] = os.environ.get(
        "SERVERS_PATH", os.path.join(BASE_DIR, "config", "servers.json")
    )
    app.config["CPU_READER"] = psutil.cpu_percent

    servers = load_servers(app.config["SERVERS_PATH"])
    init_db(app.config["DATABASE_PATH"])
    replace_servers(app.config["DATABASE_PATH"], servers)

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user"):
                return redirect(url_for("sign_in"))
            return view(*args, **kwargs)

        return wrapped

    @app.get("/")
    @app.post("/")
    def sign_in():
        if session.get("user"):
            return redirect(url_for("servers"))

        error = None
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            password_hash = password_hash_for(app.config["DATABASE_PATH"], username)
            if password_hash and check_password_hash(password_hash, password):
                session.clear()
                session["user"] = username
                return redirect(url_for("servers"))
            error = "Invalid username or password."

        return render_template("login.html", error=error)

    @app.get("/servers")
    @login_required
    def servers():
        rows = list_servers(app.config["DATABASE_PATH"])
        return render_template("servers.html", servers=rows)

    @app.get("/servers/<int:server_id>/cpu")
    @login_required
    def cpu(server_id):
        server = server_by_id(app.config["DATABASE_PATH"], server_id)
        if server is None:
            abort(404)
        return render_template(
            "cpu.html",
            server=server,
            sample=read_cpu(app.config["CPU_READER"]),
        )

    @app.get("/metrics")
    @login_required
    def metrics():
        return render_template(
            "cpu.html",
            server=None,
            sample=read_cpu(app.config["CPU_READER"]),
        )

    @app.post("/sign-out")
    def sign_out():
        session.clear()
        return redirect(url_for("sign_in"))

    return app


def load_servers(path):
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    if not raw.strip():
        raise ConfigError(f"{path} is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON") from exc
    if not isinstance(data, list) or not data:
        raise ConfigError(f"{path} is empty")
    servers = []
    for item in data:
        if not isinstance(item, dict):
            raise ConfigError(f"{path} must list servers with name and host")
        name = item.get("name")
        host = item.get("host")
        if not isinstance(name, str) or not isinstance(host, str):
            raise ConfigError(f"{path} must list servers with name and host")
        name = name.strip()
        host = host.strip()
        if not name or not host:
            raise ConfigError(f"{path} must list servers with name and host")
        servers.append((name, host))
    return servers


def init_db(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                host TEXT NOT NULL
            )
            """
        )
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (DEMO_USERNAME,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (
                    DEMO_USERNAME,
                    generate_password_hash(DEMO_PASSWORD, method=HASH_METHOD),
                ),
            )


def replace_servers(path, servers):
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM servers")
        conn.executemany(
            "INSERT INTO servers (name, host) VALUES (?, ?)",
            servers,
        )


def list_servers(path):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, host FROM servers ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def server_by_id(path, server_id):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, name, host FROM servers WHERE id = ?",
            (server_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def password_hash_for(path, username):
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return row[0]


def read_cpu(percent):
    try:
        overall = percent(interval=1)
        cores = percent(interval=1, percpu=True)
        core_values = [float(value) for value in cores]
        return {"overall": float(overall), "cores": core_values}
    except Exception:
        return None


def snapshot_db(path):
    with sqlite3.connect(path) as conn:
        users = conn.execute(
            "SELECT username, password_hash FROM users ORDER BY username"
        ).fetchall()
        servers = conn.execute(
            "SELECT id, name, host FROM servers ORDER BY id"
        ).fetchall()
    return users, servers


try:
    app = create_app()
except ConfigError as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(1) from exc


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
