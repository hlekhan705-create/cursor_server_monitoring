# Demo Server Monitoring

Read-only local demo. Sign in with the shared admin account. The password is stored only as a hash in `data/monitor.db`.

Demo login: `admin` / `admin`. Local `SECRET_KEY` default: `demo-local-secret` (override with the `SECRET_KEY` environment variable).

`/servers` and `/metrics` open after sign-in. A failed sign-in stays on the form.

## Run

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

The app listens on 127.0.0.1 only. Stop it with Ctrl+C.
