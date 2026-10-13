# OrderFlow — Order Management Portal

A web portal that turns Purchase Order (PO) PDFs into reviewed orders and routes published orders to the printing team.
It has three role-based panels: **Sales**, **Printing** and **Admin**. The full specification is in [PROJECT.md](PROJECT.md).

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy · SQLite · pdfplumber (`backend/`)
- **Frontend:** React 18 · TypeScript · Vite · lucide-react (`frontend/`)

## Quick start (Windows)

Prerequisites: Windows 10/11, Python 3.11 or newer (`py --version`), Node.js 20 or newer (`node --version`).

```powershell
cd C:\order_flow
.\setup.bat            # one time: venv, Python + npm packages, backend\.env with a random SECRET_KEY
.\start_backend.bat    # terminal 1 → API on http://127.0.0.1:8000  (docs: /docs)
.\start_frontend.bat   # terminal 2 → UI on  http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173** and sign in.

**Port 8000 already in use?** Pick another port and use it in both terminals:

```powershell
$env:PORT = "8010"; .\start_backend.bat     # terminal 1
$env:PORT = "8010"; .\start_frontend.bat    # terminal 2 (Vite proxies /api to that port)
```

**Single-window mode:** `.\start_portal.bat` builds the React app and serves the UI and API together on
http://127.0.0.1:8000 (or `%PORT%`).

**Live server:** follow [DEPLOYMENT.md](DEPLOYMENT.md) — `setup_production.bat` (runtime packages + production
build), `run_server.bat` (no dev server), daily `backup_now.bat`, HTTPS and the pre-launch security checklist.

### Login accounts (Admin, Sales, Printing)

No usernames or passwords are built into OrderFlow or written in this documentation. Each panel's login is set
in your own `backend\.env` (never committed to Git; [backend/.env.example](backend/.env.example) has empty
placeholders):

```
ADMIN_USERNAME=…      ADMIN_PASSWORD=…
SALES_USERNAME=…      SALES_PASSWORD=…
PRINTING_USERNAME=…   PRINTING_PASSWORD=…
```

On backend start, an account is created from these values **only when no account with that role exists yet**.
Existing accounts are never changed, reset or recreated (also not when renamed or deactivated). Editing a password in
`.env` later does **not** change it; use Admin → **Users** → **Reset password**. Passwords are stored only as bcrypt
hashes and never logged. Sign-in ignores capitals in the username; passwords are case-sensitive.
Password rule: at least 8 characters, mixing letters with numbers or symbols.

### Other ways to create the first Admin account

The password is never shown, stored only as a bcrypt hash, and never written to logs.

**A. Setup command.** With the backend stopped or running:

```powershell
cd C:\order_flow
.\create_admin.bat owner          # asks for the password twice at a hidden prompt
```

(Same as `cd backend; .\.venv\Scripts\python -m app.manage create-admin owner`.) Then sign in as `owner` and use
**Users** in the Admin panel for everything else.

**B. Environment variables:** `ADMIN_USERNAME` / `ADMIN_PASSWORD` as above. The backend window then prints
`Account setup: created Admin account '…'` (the password is not printed).

**C. Set or change the Admin login in one step** (backs up first, then creates the Admin or updates the existing
Admin's username and password — never a duplicate):

```powershell
cd C:\order_flow\backend
.\.venv\Scripts\python -m app.manage set-admin-credentials Admin      # hidden password prompt
```

Command-line account tools (useful if every Admin is locked out):

```powershell
cd backend
.\.venv\Scripts\python -m app.manage list-users
.\.venv\Scripts\python -m app.manage create-user priya sales --name "Priya Shah"   # roles: admin, sales, printing
.\.venv\Scripts\python -m app.manage set-password sales
.\.venv\Scripts\python -m app.manage deactivate printing
.\.venv\Scripts\python -m app.manage activate printing
```

## Admin panel

Sign in with an Admin account. Admin pages and every `/api/admin/*` endpoint are checked on the server; hiding menu
items is not the protection.

| Page | What it does |
|------|--------------|
| **Admin Dashboard** | Order counts (Draft, Live, New, Processing, Print Done, discarded), users per role, orders uploaded/published per day (14 days), oldest open print jobs, recent activity. |
| **All Orders** | Every order including drafts and discarded drafts. Search by order no., PO, customer or SKU; filter by status, printing status and a date range (uploaded / published / updated). Opening an order shows it **read-only**. |
| **Users** | Create accounts, edit name and role, activate/deactivate, reset passwords. A role change, deactivation or password reset signs that user out everywhere immediately. You cannot deactivate yourself, change your own role, or remove the last active Admin. |
| **Executive Contacts** | Executive / sales contact names offered as a dropdown on the Sales Order form. Add, edit and delete names. Names extracted from uploaded POs and names typed on a saved draft are added automatically (matched ignoring case and extra spaces, so no duplicates). Renaming or deleting a contact never changes orders. |
| **Activity Log** | Who uploaded (created), saved, edited, published and processed each order, plus sign-ins (successful and failed), user changes, settings changes and backups. Filter by text, user, action, type and dates. |
| **Settings & Backup** | Safe runtime settings (max upload size 1–50 MB, session length 15–1440 min) and on-demand backups. |

Admin can also do everything Sales can (upload, edit, save, publish, comment), edit Live orders in any printing
status (re-checked against the publish rules and logged as *Live order edited*), delete any order and restore
deleted orders. Changing the printing status and post-print photos stay with Printing.

Settings that are **not** editable in the browser on purpose: `SECRET_KEY`, file locations, time zone and the
order-number prefix. Change them in `backend\.env` and restart.

### Backups

**Create backup now** writes `backend\backups\orderflow_backup_YYYYMMDD_HHMMSS.zip` containing a consistent copy of
the database (`order_portal.db`, taken safely while the portal is running), optionally every uploaded file
(`uploads\`), and a `manifest.json`. Download it from the same page and copy it to another drive regularly.

**Scheduled backups:** `backup_now.bat` (same as `cd backend; .\.venv\Scripts\python -m app.manage backup`, add
`--no-uploads` for the database only) creates the same ZIP and records it in the Activity Log — schedule it daily
with Windows Task Scheduler. Backups are never deleted automatically.

**Restore (manual, on purpose):** stop the backend → keep a copy of the current `backend\order_portal.db` and
`backend\uploads\` → unzip the backup → put its `order_portal.db` and `uploads` folder into `backend\` → start the
backend.

### Upgrading an existing installation

The first start after this update upgrades the database in place: the `users` table is rebuilt once to allow the
Admin role. All users (same ids and password hashes), orders, files and history are kept. A safety copy is written
first to `backend\backups\pre_admin_upgrade_<date>.db`.

## Workflow

1. **Sales → Upload PO**: the PDF is stored and fields are extracted into a **Draft**. Missing, doubtful or
   inconsistent values are flagged; nothing is guessed.
2. **Sales → Review**: correct customer/address/amounts, add/edit/remove product rows, and add
   customization: per SKU (same text for every unit, **one name per unit**, logo reference/files, notes) and/or
   global (text, names, logo, notes). Each product card has **Save Changes** and the global section has
   **Save Global Changes** to save just that part; **Save draft** saves everything. None of these publish.
3. **Publish Live** (Sales confirms the review): generates `OF-YYYY-NNNNN`, records the Live timestamp, locks the
   order and puts it in the Printing queue as **New**.
4. **Printing**: queue sorted by Live date (oldest first) → open → print sheet / source PDF →
   **New → Processing → Print Done** (final and locked) → optional post-print photos.
5. Comments are available to Sales and Printing at any stage; every action is in the activity history (Admin can read all of it).

### Business rules enforced by the API

| Rule | Behaviour |
|------|-----------|
| Customization required to publish | Global text/names/logo **or** SKU-wise text/names/logo on at least one row. Notes alone do not count. |
| Individual names | If entered for a row, the count must equal the quantity (publish is blocked otherwise). |
| Shipping address | Not required to publish (that editor section was removed). |
| Review confirmation | Publish requires `reviewed: true` (the checkbox in the publish dialog). |
| Live orders | Sales edits, logo changes, re-extraction and discarding are rejected (HTTP 409). Admin may edit (publish rules re-checked). Comments still work. |
| Delete | Archives the order (kept with its history, hidden from lists and the Printing queue). Sales: Drafts and Live orders still **New**; Admin: any order. Only Admin can restore. |
| Second publish | Rejected; the original internal number is returned, no new number is generated. |
| Printing transitions | Only New → Processing → Print Done, Printing role only. Print Done is terminal. |
| Draft visibility | Printing cannot list or open Drafts (HTTP 404). |
| Concurrent edits | Every save/publish/status change checks the order `version`; stale writes get HTTP 409. |
| Line values | Kept as printed/entered; mismatches with rate × qty and subtotal are flagged, not auto-corrected. |

## Configuration (`backend/.env`)

See [backend/.env.example](backend/.env.example). Key settings: `SECRET_KEY`, `TOKEN_EXPIRE_MINUTES` (default 480),
`MAX_UPLOAD_MB` (15), `APP_TIMEZONE` (Asia/Kolkata), `ORDER_NUMBER_PREFIX` (OF),
`BACKUP_DIR` (backups), `HOST` (127.0.0.1; `0.0.0.0` = reachable from other computers), `PORT` (8000),
`ENABLE_API_DOCS` (true; set `false` on a live server), `CORS_ORIGINS`, and the login accounts
`ADMIN_*`, `SALES_*`, `PRINTING_*` (`_USERNAME` / `_PASSWORD`, see *Login accounts*). Upload size and session length can also be changed by an Admin
(Settings & Backup); saved values override `.env`.

Couriers and courier exports were removed from OrderFlow (13 October 2026). Courier values saved on older orders
remain in the database untouched but are no longer used or shown.

## Tests

```powershell
.\run_tests.bat                                   # backend tests + frontend type-check and production build
```

Or individually:

```powershell
cd backend;  .\.venv\Scripts\python -m pytest     # extraction, auth/roles, workflow, locks, section saves, admin, contacts
cd frontend; npm test                             # Vitest: form helpers, order editor, admin panel
cd frontend; npm run build                        # tsc type-check + Vite production build
```

`backend/scripts/smoke_test.py` runs an 18-step live check against **running** servers
(`python scripts/smoke_test.py http://127.0.0.1:5173`). It creates real records, so start the backend with a scratch
database (`$env:DATABASE_PATH="C:\temp\scratch.db"; $env:UPLOAD_DIR="C:\temp\scratch_uploads"`).

Test fixtures: `tests/fixtures/samples/order_73530274.pdf` is the supplied sample PO (contains customer personal
data; it is git-ignored). `tests/fixtures/layouts/*.pdf` are re-typeset from the three PO **screenshots** supplied
(status-box layout, DRAFT watermark + Seller GST block, PreTax/Tax/Total) via `tests/fixtures/make_fixtures.py`.

## Data, backup and security

- Data lives in `backend/order_portal.db` (SQLite) and `backend/uploads/` (PO PDFs, logos, photos).
  Use **Admin → Settings & Backup** (or copy both together while the backend is stopped).
- Passwords are bcrypt hashes; sessions are signed JWTs (8 h) kept in browser *session* storage and revoked on
  sign-out; repeated failed logins are throttled.
- Uploads are checked by file signature (PDF / PNG / JPG / GIF / WEBP), size-limited, stored under random names.
- Never commit `backend/.env`, the database, `uploads/`, `backups/` or customer PDFs (see `.gitignore`).
- Audit log entries never contain passwords; failed sign-ins for unknown usernames are recorded without the typed text.
- For network or production use follow [DEPLOYMENT.md](DEPLOYMENT.md): HTTPS, a kept-secret `SECRET_KEY`, real
  accounts with changed passwords, API docs off, and a tested backup/restore procedure.

## Project layout

```text
order_flow/
├── PROJECT.md, README.md, DEPLOYMENT.md, .gitignore
├── setup.bat, create_admin.bat, start_backend.bat, start_frontend.bat, start_portal.bat, run_tests.bat   (development)
├── setup_production.bat, run_server.bat, backup_now.bat                                               (live server)
├── backend/
│   ├── requirements.txt, requirements-dev.txt, .env.example, pytest.ini
│   ├── app/
│   │   ├── main.py            FastAPI app, error handlers, serves frontend/dist if built
│   │   ├── config.py          settings from .env
│   │   ├── database.py        SQLite engine/session
│   │   ├── models.py          users, orders, order_items, order_events, order_attachments, order_photos, counters
│   │   ├── schemas.py         request validation
│   │   ├── security.py        bcrypt, JWT, role guards, login throttle
│   │   ├── security_seed.py   login accounts from .env (first start only)
│   │   ├── manage.py          command line: accounts and backups
│   │   ├── backup.py          backup ZIPs (database + uploads)
│   │   ├── pdf_extract.py     coordinate-based PO extraction with warnings
│   │   ├── services.py        workflow rules (draft, publish, printing, serialisation)
│   │   └── routers/           auth, dashboard, orders, contacts, admin
│   ├── scripts/               init_env.py, smoke_test.py
│   └── tests/                 pytest suite + fixtures
└── frontend/
    ├── package.json, vite.config.ts, tsconfig.json, index.html
    └── src/
        ├── main.tsx, App.tsx, api.ts, auth.tsx, types.ts, format.ts, styles.css
        ├── components/        Layout, OrdersTable, Discussion, Files, Toast, ui
        └── pages/             Login, Dashboard, OrdersList, UploadPO, OrderPage, OrderEditor, OrderView, PrintView, admin/*
```

## API overview

All routes are under `/api` and enforce roles on the server. Interactive docs: `http://127.0.0.1:8000/docs`
(turned off when `ENABLE_API_DOCS=false`).

`POST /login` · `POST /logout` · `GET /me` · `GET /health` · `GET /dashboard` · `GET /orders` ·
`POST /orders/upload` · `GET|PUT /orders/{id}` · `POST /orders/{id}/items` · `PUT /orders/{id}/items/{item_id}` ·
`PUT /orders/{id}/global` · `GET /orders/{id}/publish-check` · `POST /orders/{id}/publish` ·
`POST /orders/{id}/re-extract` · `POST /orders/{id}/archive` (delete) · `POST /orders/{id}/restore` (Admin) ·
`POST /orders/{id}/comment` ·
`POST /orders/{id}/printing-status` · `GET /orders/{id}/source-pdf` · `GET /orders/{id}/print` ·
`POST|GET|DELETE /orders/{id}/attachments[/{aid}]` · `POST|GET /orders/{id}/photos[/{pid}]`

Admin only: `GET /admin/dashboard` · `GET /admin/orders` · `GET|POST /admin/users` · `PATCH /admin/users/{id}` ·
`POST /admin/users/{id}/reset-password` · `GET /admin/activity` · `GET|PUT /admin/settings` · `GET|POST /admin/backups` ·
`GET /admin/backups/{name}`
