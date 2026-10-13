"""Create backend/.env from .env.example with a freshly generated SECRET_KEY (never overwrites an existing .env)."""
from __future__ import annotations

import secrets
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def main() -> None:
    env = BACKEND / ".env"
    if env.exists():
        print(".env already exists - left unchanged.")
        return
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    text = text.replace("SECRET_KEY=change-me-to-a-long-random-string", f"SECRET_KEY={secrets.token_urlsafe(48)}")
    env.write_text(text, encoding="utf-8")
    print("Created backend/.env with a new random SECRET_KEY.")


if __name__ == "__main__":
    main()
