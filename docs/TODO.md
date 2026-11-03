# Implementation TODO

Do these sections in order. Each section is one small change. Finish its security and documentation boxes before the next section.

This is a local demo of a read-only CPU monitor. Scope stays inside `docs/requirements.md`. Work only in the project directory. Use a project virtualenv. Leave system packages, system Python, services, and host firewall rules unchanged.

## 1. Project initialization and basic UI

- [x] Add `.gitignore` for `.venv/`, `__pycache__/`, and `data/*.db`.
- [x] Add `requirements.txt` with `flask` and `psutil`.
- [x] Add `app.py` that starts Flask on `127.0.0.1:5000`.
- [x] Add a base template, plain CSS, and a placeholder servers page (one static card, no live data yet).
- [x] Keep the page read-only: no forms and no controls that change a server.
- [x] **Security:** Bind to `127.0.0.1` only. Leave Flask debug off in the committed app. Keep the virtualenv, database file, and any secret out of git.
- [x] **Docs:** Add `README.md` with four local commands: create a venv, activate it, `pip install -r requirements.txt`, and `python app.py`.

## 2. Sign-in and unit tests

- [x] On startup, create `data/monitor.db` and a `users` table (`username`, `password_hash`).
- [x] Insert `admin` once, with a Werkzeug PBKDF2-SHA256 hash of the password `admin`. Leave an existing row as it is on later startups.
- [x] Add the sign-in page (the only form) and a sign-out action. A match starts a Flask session. A mismatch redisplays the form with one generic message.
- [x] Add unit tests for: the stored value is a hash, the correct password passes, a wrong password fails, and a second startup does not replace the hash.
- [x] Monitoring pages stay read-only. Sign-in is the only write the user can make, and it writes a session only.
- [x] **Security:** Store the password only as a hash. Set the session cookie `HttpOnly` and `SameSite=Lax`. Read `SECRET_KEY` from the environment, and document one local demo value in the README.
- [x] **Docs:** Document the demo login `admin` / `admin` and that the hash is in `data/monitor.db`.

## 3. Close pages until sign-in

- [x] Send every route except sign-in back to the sign-in page when the session is missing.
- [x] After sign-out, the servers page is unreachable until the next successful sign-in.
- [x] Add tests for an anonymous redirect and a signed-in page load.
- [x] **Security:** Server name, host, and CPU stay off the response until the session exists. The signed-in pages remain read-only.
- [x] **Docs:** Note the redirect rule in the README.

## 4. Server list from config

- [x] Add `config/servers.json` with one entry: name `This server`, host `localhost`.
- [x] On startup, read that file and replace the `servers` rows in SQLite. Stop with a clear error when the file is empty or invalid JSON.
- [x] Show those rows on the servers page as read-only cards (name, host, link to CPU). No add, edit, or delete controls.
- [x] Add tests for a valid file, invalid JSON, and a page with no mutating controls.
- [x] **Security:** Treat the file as data. Read CPU on this machine only. Open no connection to `host`.
- [x] **Docs:** Say that a config edit applies after a restart.

## 5. Live CPU page

- [x] Read overall and per-core CPU with `psutil.cpu_percent` and a 1-second interval.
- [x] Render the overall percent and one bar per core. Refresh the page every 5 seconds.
- [x] On a read failure, show a short error and leave SQLite unchanged.
- [x] Add tests with a stand-in for `psutil`: success returns overall plus cores, and failure writes nothing.
- [x] **Security:** Keep the page read-only. Collect from this process’s machine only. Run no shell and change no host setting.
- [x] **Docs:** Describe the CPU page and the 5-second refresh in the README.

## 6. CI/CD with GitHub Actions

- [x] Add `.github/workflows/ci.yml`, triggered on push and pull request.
- [x] The workflow installs `requirements.txt` and runs the unit tests with `pytest`.
- [x] **Security:** The workflow stores no secrets and uses no deploy keys. Package install is the only network step. It does not change the runner beyond the job, and it does not deploy the app.
- [x] **Docs:** State that CI is this workflow, and delivery is still local: after it is green, run `python app.py` on this machine and open `http://127.0.0.1:5000`.

## 7. Acceptance check

- [x] Walk the acceptance list in `docs/requirements.md` once on this machine.
- [x] Anonymous visit to the servers or CPU page opens sign-in.
- [x] `admin` / `admin` opens the server list. Any other password stays on sign-in.
- [x] The list matches `config/servers.json` and has no add, edit, or delete controls.
- [x] The CPU page shows overall and per-core percents and updates every 5 seconds.
- [x] Sign-out returns to sign-in, and the other pages stay closed.
- [x] A restart keeps the admin hash and reloads servers from the config file.
- [ ] The process listens on `127.0.0.1:5000` only.
- [x] **Security:** Confirm the cookie flags, localhost bind, hashed password, and read-only monitoring pages.
- [x] **Docs:** Leave the README run steps as the four local commands above.
