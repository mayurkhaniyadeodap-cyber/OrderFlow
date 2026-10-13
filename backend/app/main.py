"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text  # pyright: ignore[reportMissingImports]

try:
    from sqlalchemy.orm.exc import StaleDataError  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover
    from sqlalchemy.exc import StaleDataError  # pyright: ignore[reportMissingImports]

from .config import BACKEND_DIR, settings
from .database import SessionLocal, configure_database
from . import audit, contacts, runtime_settings
from .routers import admin, auth, contacts as contacts_router, dashboard, orders
from .security_seed import SKIPPED, bootstrap_accounts_from_env

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
log = logging.getLogger("orderflow")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    configure_database(settings.database_path, settings.backup_dir)  # upgrades old schemas after a safety copy
    with SessionLocal() as db:
        # Admin / Sales / Printing accounts from the environment, only for roles with no account yet.
        # Existing accounts are never changed; passwords are never logged.
        for message in bootstrap_accounts_from_env(db):
            if not message.startswith(SKIPPED):
                log.warning("Account setup: %s", message)
        runtime_settings.load_overrides(db)
        added = contacts.backfill_from_orders(db)  # one-time: executive names already on orders (orders unchanged)
        if added is not None:
            audit.record(db, "system", "contacts_backfilled", None, f"{added} contact(s) imported from existing orders.")
            db.commit()
            log.warning("Executive contacts: %d imported from existing orders (one-time).", added)
    yield


# API documentation pages (/docs, /redoc, /openapi.json) can be switched off on a live server: ENABLE_API_DOCS=false
_docs = settings.enable_api_docs
app = FastAPI(title="OrderFlow — Order Management Portal", version="1.0.0", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url="/redoc" if _docs else None,
              openapi_url="/openapi.json" if _docs else None)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(StaleDataError)
async def stale_data(_request: Request, _exc: StaleDataError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": {
        "message": "This order was changed by someone else at the same time. Reload and try again.",
        "code": "version_conflict"}})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        readable = " → ".join(f"row {int(p) + 1}" if p.isdigit() else p.replace("_", " ") for p in loc)
        msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
        errors.append(f"{readable}: {msg}" if readable else msg)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        content={"detail": {"message": "Please correct the highlighted values.", "errors": errors}})


@app.get("/api/health", tags=["health"])
def health() -> dict:
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ok", "database": "ok", "uploads_dir": settings.upload_dir.is_dir(),
            "secret_configured": not settings.secret_is_ephemeral}


for module in (auth, dashboard, orders, contacts_router, admin):
    app.include_router(module.router, prefix="/api")


# Unknown API routes answer 404 for every method. Without this, a non-GET request to a missing route would hit
# the GET-only React catch-all below and report a misleading "405 Method Not Allowed".
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def unknown_api_route(path: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": {
        "message": f"API route /api/{path} does not exist on the running backend. If the portal was just updated, "
                   "restart start_backend.bat.",
        "code": "unknown_api_route"}})


# Serve the built React app (frontend/dist) when present so the portal can run on a single port.
if FRONTEND_DIST.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("assets/"):  # missing build files are real 404s
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        candidate = (FRONTEND_DIST / path).resolve()
        if path and FRONTEND_DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
