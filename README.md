# Demo Server Monitoring

Read-only local demo. Sign in with the shared admin account. The password is stored only as a hash in `data/monitor.db`.

Demo login: `admin` / `admin`. Local `SECRET_KEY` default: `demo-local-secret` (override with the `SECRET_KEY` environment variable).

`/servers`, `/metrics`, and each CPU page open after sign-in. A failed sign-in stays on the form.

Server names and hosts are read from `config/servers.json`. A config edit applies after a restart. The file is data: CPU is read on this machine only, and the app does not connect to `host`.

The CPU page shows the overall percent and one bar per core. It reloads every 5 seconds. A failed reading shows a short error and does not change `data/monitor.db`.

CI is `.github/workflows/ci.yml`. It installs the requirements and runs the unit tests on push and pull request. It does not deploy. After it is green, run `python app.py` on this machine and open http://127.0.0.1:5000.

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

## Development
Development changes are made on the dev branch and merged into main through pull requests.
