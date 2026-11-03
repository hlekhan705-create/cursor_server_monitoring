import os
import sqlite3
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

DEMO_USERNAME = "admin"
DEMO_PASSWORD = "admin"
HASH_METHOD = "pbkdf2:sha256"


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "demo-local-secret")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["DATABASE_PATH"] = os.environ.get(
        "DATABASE_PATH", os.path.join("data", "monitor.db")
    )
    init_db(app.config["DATABASE_PATH"])

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
        return render_template("servers.html")

    @app.get("/metrics")
    @login_required
    def metrics():
        return render_template("metrics.html")

    @app.post("/sign-out")
    def sign_out():
        session.clear()
        return redirect(url_for("sign_in"))

    return app


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


def password_hash_for(path, username):
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return row[0]


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
