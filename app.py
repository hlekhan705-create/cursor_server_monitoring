import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from functools import wraps

import psutil
from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

DEMO_USERNAME = "admin"
DEMO_PASSWORD = "admin"
HASH_METHOD = "pbkdf2:sha256"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERNAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,31}")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
REMOTE_METRICS = r"""
set -eu
cpu_line() { awk '/^cpu / {t=0; for (i=2;i<=NF;i++) t+=$i; print t, $5+$6}' /proc/stat; }
a=$(cpu_line)
sleep 0.2
b=$(cpu_line)
cpu=$(awk -v a="$a" -v b="$b" 'BEGIN {split(a,x," "); split(b,y," "); dt=y[1]-x[1]; di=y[2]-x[2]; if (dt<=0) print "0.0"; else printf "%.1f", (dt-di)/dt*100}')
mem=$(awk '/MemTotal:/ {t=$2} /MemAvailable:/ {a=$2} END {if (t>0) printf "%.1f", (t-a)/t*100; else print "0.0"}' /proc/meminfo)
disk=$(df -P -x tmpfs -x devtmpfs -x squashfs -x overlay -x efivarfs -x nsfs 2>/dev/null | awk 'NR>1 {pct=$5; gsub("%","",pct); pct=pct+0; mount=$6; for (i=7;i<=NF;i++) mount=mount" "$i; if (!seen || pct>=max) {max=pct; best=mount; seen=1}} END {if (!seen) print "0.0 /"; else printf "%.1f %s", max, best}')
printf 'cpu %s\nmem %s\ndisk %s\n' "$cpu" "$mem" "$disk"
"""


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
    app.config["HOST_READER"] = read_host
    app.config["REMOTE_READER"] = read_remote
    app.config["SSH_IDENTITY"] = os.environ.get(
        "MONITOR_SSH_IDENTITY",
        os.path.expanduser("~/.ssh/monitoring_ed25519"),
    )

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
        return render_template(
            "servers.html",
            servers=servers_with_readings(app),
            error=None,
        )

    @app.post("/servers")
    @login_required
    def add_server_view():
        name = request.form.get("name", "")
        host = request.form.get("host", "")
        try:
            add_server(
                app.config["DATABASE_PATH"],
                app.config["SERVERS_PATH"],
                name,
                host,
            )
        except ValueError as exc:
            return render_template(
                "servers.html",
                servers=servers_with_readings(app),
                error=str(exc),
            )
        return redirect(url_for("servers"))

    @app.post("/servers/<int:server_id>/remove")
    @login_required
    def remove_server_view(server_id):
        try:
            remove_server(
                app.config["DATABASE_PATH"],
                app.config["SERVERS_PATH"],
                server_id,
            )
        except ValueError as exc:
            return render_template(
                "servers.html",
                servers=servers_with_readings(app),
                error=str(exc),
            )
        return redirect(url_for("servers"))

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
        port = item.get("port")
        username = item.get("username")
        if port in (None, ""):
            port = None
        elif isinstance(port, str) and port.isdigit():
            port = int(port)
        if isinstance(port, bool) or (
            port is not None and (not isinstance(port, int) or not 1 <= port <= 65535)
        ):
            raise ConfigError(f"{path} has a server with an invalid port")
        if username in (None, ""):
            username = None
        elif not isinstance(username, str) or not USERNAME_RE.fullmatch(username.strip()):
            raise ConfigError(f"{path} has a server with an invalid username")
        else:
            username = username.strip()
        servers.append(
            {"name": name, "host": host, "port": port, "username": username}
        )
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
                host TEXT NOT NULL,
                port INTEGER,
                username TEXT
            )
            """
        )
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(servers)").fetchall()
        }
        if "port" not in columns:
            conn.execute("ALTER TABLE servers ADD COLUMN port INTEGER")
        if "username" not in columns:
            conn.execute("ALTER TABLE servers ADD COLUMN username TEXT")
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


def add_server(db_path, config_path, name, host):
    name = (name or "").strip()
    host = (host or "").strip()
    if not name or not host:
        raise ValueError("Enter a name and a host.")
    if len(name) > 80 or len(host) > 253:
        raise ValueError("Name or host is too long.")
    if any(character in name + host for character in "\r\n\t"):
        raise ValueError("Name and host cannot include line breaks.")
    servers = load_servers(config_path)
    if any(item["name"] == name and item["host"] == host for item in servers):
        raise ValueError("That server is already listed.")
    servers.append({"name": name, "host": host, "port": None, "username": None})
    save_servers(config_path, servers)
    replace_servers(db_path, servers)


def remove_server(db_path, config_path, server_id):
    row = server_by_id(db_path, server_id)
    if row is None:
        raise ValueError("That server is not listed.")
    servers = load_servers(config_path)
    if len(servers) <= 1:
        raise ValueError("At least one server must remain.")
    kept = []
    removed = False
    for item in servers:
        if not removed and item["name"] == row["name"] and item["host"] == row["host"]:
            removed = True
            continue
        kept.append(item)
    if not removed or not kept:
        raise ValueError("At least one server must remain.")
    save_servers(config_path, kept)
    replace_servers(db_path, kept)


def save_servers(path, servers):
    payload = []
    for item in servers:
        entry = {"name": item["name"], "host": item["host"]}
        if item.get("port"):
            entry["port"] = item["port"]
        if item.get("username"):
            entry["username"] = item["username"]
        payload.append(entry)
    directory = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(dir=directory, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def fullest_disk():
    best_percent = None
    best_mount = None
    skipped = {"squashfs", "overlay", "tmpfs", "devtmpfs", "nsfs", "proc", "sysfs", "autofs"}
    for part in psutil.disk_partitions(all=False):
        if not part.mountpoint or part.fstype in skipped:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        if best_percent is None or usage.percent > best_percent:
            best_percent = float(usage.percent)
            best_mount = part.mountpoint
    if best_mount is None:
        usage = psutil.disk_usage("/")
        return "/", float(usage.percent)
    return best_mount, best_percent


def read_host():
    try:
        cpu = float(psutil.cpu_percent(interval=0.1))
        memory = float(psutil.virtual_memory().percent)
        mount, disk = fullest_disk()
        return {
            "online": True,
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "mount": mount,
        }
    except Exception:
        return {
            "online": False,
            "cpu": None,
            "memory": None,
            "disk": None,
            "mount": None,
        }


def empty_reading():
    return {
        "online": False,
        "cpu": None,
        "memory": None,
        "disk": None,
        "mount": None,
    }


def parse_remote_metrics(text):
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(" ")
        if key:
            values[key] = rest.strip()
    disk_text = values["disk"]
    disk_value, _, mount = disk_text.partition(" ")
    return {
        "online": True,
        "cpu": float(values["cpu"]),
        "memory": float(values["mem"]),
        "disk": float(disk_value),
        "mount": mount or "/",
    }


def read_remote(host, port, username, identity):
    if (
        not isinstance(host, str)
        or not HOST_RE.fullmatch(host)
        or not isinstance(username, str)
        or not USERNAME_RE.fullmatch(username)
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or not identity
        or not os.path.isfile(identity)
    ):
        return empty_reading()
    try:
        result = subprocess.run(
            [
                "ssh",
                "-i",
                identity,
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=8",
                "-p",
                str(port),
                f"{username}@{host}",
                REMOTE_METRICS,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return empty_reading()
        return parse_remote_metrics(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return empty_reading()


def servers_with_readings(app):
    rows = list_servers(app.config["DATABASE_PATH"])
    local = None
    for row in rows:
        if row.get("username"):
            try:
                reading = app.config["REMOTE_READER"](
                    row["host"],
                    row.get("port") or 22,
                    row["username"],
                    app.config["SSH_IDENTITY"],
                )
            except Exception:
                reading = None
        else:
            if local is None:
                try:
                    local = app.config["HOST_READER"]()
                except Exception:
                    local = None
            reading = local
        if not reading or not reading.get("online"):
            reading = empty_reading()
        row["reading"] = reading
    return rows


def replace_servers(path, servers):
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM servers")
        conn.executemany(
            "INSERT INTO servers (name, host, port, username) VALUES (?, ?, ?, ?)",
            [
                (item["name"], item["host"], item.get("port"), item.get("username"))
                for item in servers
            ],
        )


def list_servers(path):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, host, port, username FROM servers ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def server_by_id(path, server_id):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, name, host, port, username FROM servers WHERE id = ?",
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
