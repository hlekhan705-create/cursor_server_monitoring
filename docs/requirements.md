# Demo Server Monitoring — Requirements

**Status:** Demo scope, agreed for a local-only build  
**App:** Read-only CPU monitor for the Linux machine it runs on  
**Stack:** Python, Flask, SQLite, server-rendered pages

## Problem

Internal teams currently sign in to Linux servers to see live CPU usage. This demo replaces that check with a local web page. It shows current CPU for the machine where the app is running. No one needs a shell account to look.

## Users

Internal L1, L2, and L3 staff across infrastructure and application teams. Everyone who can open the app signs in as the same demo admin and can only view data.

## Decisions for this demo

| Topic | Choice |
| --- | --- |
| What is monitored | This Linux machine only. No SSH. |
| Server list | Hand-edited config file. The UI has no add, edit, or remove. |
| Sign-in | Username `admin`. Password checked against a hash. Demo password is `admin`. |
| Metrics | CPU only: overall percent and per-core percent. |
| Freshness | Current snapshot. The page refreshes every 5 seconds. No history and no charts. |
| Storage | Local SQLite file. Server rows are reloaded from the config file on startup. |

## Goals

- Sign in with the demo admin account.
- See the local host in a server list loaded from config.
- See live overall and per-core CPU without a terminal.
- Keep the UI read-only after sign-in.
- Start the app on this machine with a few commands.

## Out of scope

- Remote hosts, SSH, agents, or credentials for other machines
- Memory, swap, network, ports, disk, load, or uptime
- History, charts, alerts, or exports
- Adding or editing servers in the UI
- Extra users, roles, or a change-password screen
- HTTPS, reverse proxy, or any host other than this machine

## Features

### 1. Read-only UI

After sign-in, the app only displays data. There are no forms except the login form, and no buttons that change servers or the host.

Pages:

- **Sign in** — username and password.
- **Servers** — one card for the local host (name and host from config) and a link to its CPU page.
- **CPU** — overall CPU percent and one row per core. Values come from a fresh reading on each load.

The CPU page reloads itself every 5 seconds. A failed reading shows a short error on the page and does not change stored server data.

Visual design stays simple and readable: one column on a narrow window, cards on a wide window, a clear percent for overall CPU, and a bar per core. Use plain CSS served by Flask. No frontend build step.

### 2. Sign in

- The only account is username `admin`.
- The password is stored as a Werkzeug password hash (PBKDF2-SHA256) in SQLite, never as plain text.
- On first startup, if that user row is missing, the app inserts `admin` with the hash of `admin`.
- Later startups do not overwrite the hash.
- A correct password starts a Flask session cookie. A wrong password stays on the sign-in page with a generic failure message.
- Every page except sign-in requires a session. **Sign out** clears the session and returns to sign-in.
- The demo password is documented here so a local user can log in: `admin` / `admin`.

### 3. Servers from a config file

The UI does not create servers. Hosts are declared in `config/servers.json`. For this demo the file contains the local machine only:

```json
[
  {
    "name": "This server",
    "host": "localhost"
  }
]
```

- `name` is the label on the card.
- `host` is shown as text. Collection always uses the local machine (psutil). The demo does not connect to `host`.
- On startup the app replaces the server rows in SQLite with the entries in this file.
- An empty file or invalid JSON stops startup with a clear error.
- More than one entry is stored and listed, but each entry still shows this machine’s CPU. Remote collection is out of scope.

## Data

SQLite file: `data/monitor.db` (created on startup).

| Table | Columns | Notes |
| --- | --- | --- |
| `users` | `username` (primary key), `password_hash` | Seed `admin` once. |
| `servers` | `id`, `name`, `host` | Rebuilt from `config/servers.json` on startup. |

CPU readings are not stored. Each page load reads the current sample and discards it.

## Collection

- Use `psutil.cpu_percent` for overall CPU and for each core.
- Use a 1-second interval so the first sample is not a zero placeholder.
- The web process and the collector run on the same machine.
- Bind the site to `127.0.0.1` only.

## Local run

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` and sign in with `admin` / `admin`.

Expected packages: `flask`, `psutil`. Password hashing uses Werkzeug, which Flask already installs.

Stop the app with Ctrl+C. Restart it after any edit to `config/servers.json`.

## Acceptance

- Unauthenticated visits to the server list or CPU page redirect to sign-in.
- `admin` / `admin` opens the server list. Any other password does not.
- The server list shows the name and host from `config/servers.json` and has no add, edit, or delete controls.
- The CPU page shows one overall percent and one percent per core, and updates every 5 seconds without a manual reload.
- Sign out returns to the sign-in page, and the server pages are unreachable until the next sign-in.
- Restarting the app keeps the admin hash and reloads servers from the config file.
- The app listens on `127.0.0.1:5000` only.
