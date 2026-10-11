"""Local early-access signup storage; use a managed database before scaling."""
from pathlib import Path
import re
import sqlite3


def save_signup(email: str, consent: bool, database: Path) -> None:
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email):
        raise ValueError("Enter a valid email address.")
    if not consent:
        raise ValueError("Please agree to receive the launch update.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database, timeout=10) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS signups (email TEXT PRIMARY KEY, consent INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        connection.execute("INSERT OR IGNORE INTO signups(email, consent) VALUES (?, ?)", (email, 1))
    database.chmod(0o600)
