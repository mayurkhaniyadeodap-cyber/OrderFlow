from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

warnings.filterwarnings("ignore", message="SECRET_KEY is not set")

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.security import login_throttle  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
REAL_PO = FIXTURES / "samples" / "order_73530274.pdf"
IMAGE_ONLY_PDF = FIXTURES / "samples" / "image_only_logo.pdf"
LOGO_JPEG = FIXTURES / "samples" / "logo_khodiyar.jpeg"
MEET_PAPERS = FIXTURES / "layouts" / "meet_papers_draft.pdf"
ANNESHA = FIXTURES / "layouts" / "annesha_new_status_box.pdf"
RIYA = FIXTURES / "layouts" / "riya_marketing_processing.pdf"
SAMPLES = FIXTURES / "samples"


# The real sample PO (customer data) is kept out of Git, so a fresh checkout such as GitHub Actions does not have it.
# Tests that need a missing sample file are reported as skipped there; on a PC with the samples they all run.
def _skip_if_sample_missing(exc: FileNotFoundError) -> None:
    missing = Path(str(exc.filename or ""))
    if SAMPLES.resolve() in missing.resolve().parents:
        pytest.skip(f"private sample file not available: {missing.name} (kept out of Git)")


def sample(path: Path) -> Path:
    """A private sample file, for code that turns a missing file into a result instead of an error."""
    if not path.exists():
        pytest.skip(f"private sample file not available: {path.name} (kept out of Git)")
    return path


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    try:
        return (yield)
    except FileNotFoundError as exc:
        _skip_if_sample_missing(exc)
        raise


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        return (yield)
    except FileNotFoundError as exc:
        _skip_if_sample_missing(exc)
        raise


# Test-only passwords (never the real ones from backend/.env). Sales and Printing accounts are created from these
# environment variables when the app starts; tests that need an Admin add one (see the `admin` fixture).
SALES_PASSWORD = "Test-Sales-Pass-1"
PRINTING_PASSWORD = "Test-Print-Pass-1"
TEST_ACCOUNT_ENV = {"SALES_USERNAME": "sales", "SALES_PASSWORD": SALES_PASSWORD,
                    "PRINTING_USERNAME": "printing", "PRINTING_PASSWORD": PRINTING_PASSWORD}


@pytest.fixture(autouse=True)
def account_env(monkeypatch):
    """Replace the account variables loaded from backend/.env so real credentials never reach a test."""
    for prefix in ("ADMIN", "SALES", "PRINTING"):
        for suffix in ("USERNAME", "PASSWORD"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    for name, value in TEST_ACCOUNT_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    # runtime settings can be changed by Admin endpoints during a test: restore them afterwards
    for name in ("max_upload_bytes", "token_expire_minutes"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    login_throttle._fails.clear()
    with TestClient(app) as c:
        yield c


ADMIN_PASSWORD = "Admin-Pass-2026"


def make_user(username: str, role: str, password: str = ADMIN_PASSWORD, active: bool = True) -> None:
    from app.database import SessionLocal
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        db.add(User(username=username, role=role, password_hash=hash_password(password), is_active=active))
        db.commit()


@pytest.fixture()
def admin(client):
    make_user("admin", "admin")
    return login(client, "admin", ADMIN_PASSWORD)


def login(client: TestClient, username: str = "sales", password: str | None = None) -> dict[str, str]:
    password = password or {"sales": SALES_PASSWORD, "printing": PRINTING_PASSWORD}[username]
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def sales(client):
    return login(client, "sales")


@pytest.fixture()
def printing(client):
    return login(client, "printing")


def upload(client: TestClient, headers: dict, path: Path = REAL_PO, name: str | None = None) -> dict:
    with open(path, "rb") as fh:
        r = client.post("/api/orders/upload", headers=headers,
                        files={"file": (name or path.name, fh, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


EDITABLE = (
    "po_number", "source_status", "source_order_date", "customer_name", "billing_address", "shipping_name",
    "shipping_address", "contact", "email", "gstin", "executive", "subtotal", "packaging_charges",
    "processing_charges", "additional_charges", "tax", "total", "global_customization", "global_names",
    "global_logo_reference", "global_notes",
)
ITEM_KEYS = (
    "id", "sku", "product_name", "quantity", "rate", "original_rate", "value", "weight", "hsn", "tax", "location",
    "customization_names", "customization_text", "logo_reference", "notes",
)


def payload(order: dict, **changes) -> dict:
    """Build a full Draft save payload from an order detail response."""
    body = {k: order[k] for k in EDITABLE}
    body["version"] = order["version"]
    body["items"] = [{k: item[k] for k in ITEM_KEYS} for item in order["items"]]
    body.update(changes)
    return body


def save(client: TestClient, headers: dict, order: dict, **changes) -> dict:
    r = client.put(f"/api/orders/{order['id']}", headers=headers, json=payload(order, **changes))
    assert r.status_code == 200, r.text
    return r.json()


def publish(client: TestClient, headers: dict, order: dict, reviewed: bool = True):
    return client.post(f"/api/orders/{order['id']}/publish", headers=headers,
                       json={"version": order["version"], "reviewed": reviewed})


def make_live(client: TestClient, headers: dict, path: Path = REAL_PO,
              global_customization: str = "Print logo on every unit") -> dict:
    order = upload(client, headers, path)
    order = save(client, headers, order, global_customization=global_customization)
    r = publish(client, headers, order)
    assert r.status_code == 200, r.text
    return r.json()
