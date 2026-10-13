# OrderFlow — Live Server Deployment Guide

This guide moves OrderFlow from the development PC to a live server **without losing any orders, users, files or
history**. Read the security checklist (section 7) before staff start using it.

## 1. What runs on the live server

One Python process serves both the web app (the built React files in `frontend/dist`) and the API on one port.
The Vite development server (`start_frontend.bat`) is **never** used on a live server.

| Piece | Live server |
|-------|-------------|
| Backend + built web app | `run_server.bat` (Windows) or the `uvicorn` command in section 5C (Linux) |
| Database | `backend/order_portal.db` (SQLite) — together with `order_portal.db-wal` / `-shm` while running |
| Files | `backend/uploads/` (PO PDFs, logos, photos) |
| Backups | `backend/backups/` (ZIP files) |
| Settings / secrets | `backend/.env` |

## 2. What to copy to the server

**Copy (the code):** `backend/app/`, `backend/scripts/init_env.py`, `backend/requirements.txt`, `backend/.env.example`,
`frontend/` **without** `node_modules/` and `dist/`, and the root `.bat` files.

**Do not copy:** `backend/.venv/`, `frontend/node_modules/` (they are recreated by the setup script),
`backend/tests/` and `backend/scripts/smoke_test.py` (development only — `tests/fixtures/samples/` contains a real
customer PO), `.vscode/`.

**Your data — move it with a backup, not by copying live files:**

1. On the current PC: Admin → **Settings & Backup** → **Create backup now** (or run `backup_now.bat`).
2. Copy that ZIP (and `backend/.env`, which holds your `SECRET_KEY`) to the server over a private channel.
3. On the server, before the first start: unzip it, put `order_portal.db` into `backend/` and the `uploads` folder into
   `backend/uploads/`. Do **not** copy a running database's `.db` file on its own — its newest changes may still be in
   the `-wal` file; the backup ZIP is always consistent.

## 3. Install (Windows server)

Prerequisites: Python 3.11+ and Node.js 20+ (Node is only needed to build the web app).

```powershell
cd C:\OrderFlow
.\setup_production.bat     # runtime packages only, creates backend\.env if missing, builds the web app
```

`setup_production.bat` never touches the database, uploads or backups. Run it again after every code update.

## 4. Production settings (`backend\.env`)

Keep your existing `SECRET_KEY` (changing it signs everyone out). Set:

```ini
ENABLE_API_DOCS=false
PORT=8000
HOST=127.0.0.1            # see section 5 for the right value
CORS_ORIGINS=             # leave empty: the web app is served from the same address as the API
```

Login accounts (`ADMIN_*`, `SALES_*`, `PRINTING_*` — `_USERNAME` / `_PASSWORD`) are only used to create an account
for a role that has none yet. When you move your existing database, the accounts and passwords already in it are
kept as they are; these values do not change them.

## 5. Choose how staff reach it

### A. Office network only (Windows)

1. `HOST=0.0.0.0` in `backend\.env`.
2. Allow the port in Windows Defender Firewall for the **Private** network only:
   `New-NetFirewallRule -DisplayName "OrderFlow" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow`
3. Staff open `http://<server-name-or-IP>:8000`.

Traffic inside the office is not encrypted (HTTP). That is common for internal tools, but use option B if staff
connect over Wi-Fi you do not trust or from outside the office.

### B. Reachable over the internet (Windows, with HTTPS)

Never expose port 8000 directly. Keep `HOST=127.0.0.1` and put a reverse proxy with a TLS certificate in front:

* **Caddy** (simplest; free automatic certificates) — `Caddyfile`:
  ```
  orders.example.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```
* or **IIS** with URL Rewrite + Application Request Routing proxying to `http://127.0.0.1:8000`, with an HTTPS binding.

Open only ports 80/443 in the firewall. Staff use `https://orders.example.com`.

### C. Linux server / VPS

```bash
cd /opt/orderflow/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python scripts/init_env.py
cd ../frontend && npm ci && npm run build
```

`/etc/systemd/system/orderflow.service`:

```ini
[Unit]
Description=OrderFlow
After=network.target

[Service]
WorkingDirectory=/opt/orderflow/backend
ExecStart=/opt/orderflow/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
User=orderflow

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now orderflow`, then put Caddy or nginx with HTTPS in front as in 5B. Daily backup via cron:
`0 21 * * * cd /opt/orderflow/backend && .venv/bin/python -m app.manage backup`.

## 6. Run it automatically (Windows)

Use **Task Scheduler** (built in) or a service wrapper such as NSSM.

Task Scheduler:

1. Create Task → *Run whether user is logged on or not*, *Run with highest privileges*.
2. Trigger: **At startup**. Action: Start a program → `C:\OrderFlow\run_server.bat`, "Start in": `C:\OrderFlow`.
3. Settings: *If the task fails, restart every 1 minute*; untick *Stop the task if it runs longer than…*.

**Daily backup:** a second task, Trigger *Daily* (e.g. 21:00), Action `C:\OrderFlow\backup_now.bat`. Backups are
never deleted automatically — copy `backend\backups` to another drive or computer regularly and remove old ZIPs by
hand when they are safely stored elsewhere.

## 7. Security checklist before going live

- [ ] **Strong, private passwords** on every account (Admin, Sales, Printing). Passwords used during development
      or shared in chat/email should be changed: Admin → **Users** → **Reset password**. Prefer real named accounts
      per person.
- [ ] `ENABLE_API_DOCS=false`.
- [ ] `SECRET_KEY` is a long random value (not `change-me…`) and `.env` (secret key and login passwords) is readable
      only by the account running OrderFlow and never committed or shared.
- [ ] Internet access only through HTTPS (section 5B / 5C).
- [ ] Daily backup task created and backups copied off the server.
- [ ] `backend\backups` and `backend\uploads` are not shared on the network (they contain customer data and, in
      backups, password hashes).

## 8. Restore a backup

1. Stop OrderFlow (stop the task/service).
2. Keep a copy of the current `backend\order_portal.db*` files and `backend\uploads\`.
3. Unzip the backup; put `order_portal.db` into `backend\` (delete the old `-wal`/`-shm` files after keeping the copy)
   and its `uploads` folder into `backend\uploads\`.
4. Start OrderFlow.

## 9. Update to a newer version

1. Create a backup (Settings & Backup or `backup_now.bat`).
2. Stop OrderFlow. Replace the code folders (never `backend\.env`, the database, `uploads` or `backups`).
3. Run `setup_production.bat`, then start OrderFlow. Database upgrades run automatically on start and always save a
   safety copy in `backend\backups` first.

## 10. Known items

* `react-router-dom` 6.30.6 still has two moderate advisories whose fix requires React Router 7 (a major upgrade,
  planned separately). OrderFlow only links to its own fixed pages and does not use the affected loader/SSR features.
* `vite`, `vitest`, `esbuild` advisories affect development tools only; they are not part of the built app and never
  run on the live server.
* Old `orders.courier` database column: kept intentionally (unused) so no order data had to be rewritten.
