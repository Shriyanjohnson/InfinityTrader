"""Beta accounts with Argon2id, opaque expiring sessions, and one-time recovery codes."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import threading

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

from settings import data_root

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
HASH_CAPACITY = threading.BoundedSemaphore(2)


def _hash_secret(secret):
    if not HASH_CAPACITY.acquire(timeout=2):
        raise ValueError("Account service is busy. Please try again shortly.")
    try:
        return HASHER.hash(secret)
    finally:
        HASH_CAPACITY.release()


def _verify_secret(encoded, secret):
    if not HASH_CAPACITY.acquire(timeout=2):
        raise ValueError("Account service is busy. Please try again shortly.")
    try:
        return HASHER.verify(encoded, secret)
    finally:
        HASH_CAPACITY.release()


DUMMY_HASH = _hash_secret(secrets.token_urlsafe(32))
TERMS_VERSION = "beta-1"


@contextmanager
def database():
    root = data_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "accounts.sqlite3"
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL, created_at INTEGER NOT NULL,
          terms_version TEXT NOT NULL, watchlist TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL,
          expires_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(bucket TEXT NOT NULL, at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket, at);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, owner TEXT NOT NULL,
          category TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL);
        """)
        connection.execute("INSERT OR IGNORE INTO metadata VALUES ('rate_salt', ?)", (secrets.token_hex(32),))
        connection.commit()
        path.chmod(0o600)
        yield connection
    finally:
        connection.close()


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _limit(action, username, client, now):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        salt = connection.execute("SELECT value FROM metadata WHERE key='rate_salt'").fetchone()[0]
        client_hash = hmac.new(salt.encode(), str(client).encode(), hashlib.sha256).hexdigest()
        buckets = [(f"{action}:global", 120), (f"{action}:ip:{client_hash}", 20), (f"{action}:user:{username}", 12)]
        if action == "register":
            buckets = [(f"{action}:global", 40), (f"{action}:ip:{client_hash}", 5)]
        connection.execute("DELETE FROM attempts WHERE at<?", (now - 86400,))
        for bucket, maximum in buckets:
            count = connection.execute("SELECT count(*) FROM attempts WHERE bucket=? AND at>?", (bucket, now - 900)).fetchone()[0]
            if count >= maximum:
                raise ValueError("Too many attempts. Please wait 15 minutes before trying again.")
        connection.executemany("INSERT INTO attempts VALUES (?, ?)", [(bucket, now) for bucket, _ in buckets])
        connection.commit()


def _password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("Use a password between 12 and 128 characters.")


def register(username, password, consent, client="unknown", now=None):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
        raise ValueError("Use 3–32 letters, numbers, or underscores for your username.")
    _password(password)
    if not consent:
        raise ValueError("Accept the beta terms and privacy notice to create an account.")
    stamp = int(time.time() if now is None else now)
    _limit("register", username, client, stamp)
    owner, recovery = secrets.token_hex(16), secrets.token_urlsafe(32)
    password_hash, recovery_hash = _hash_secret(password), _hash_secret(recovery)
    with database() as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT count(*) FROM users").fetchone()[0] >= int(os.environ.get("INFINITY_MAX_ACCOUNTS", "200")):
            raise ValueError("This beta cohort is full. Please check back later.")
        try:
            connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (owner, username, password_hash, recovery_hash, stamp, TERMS_VERSION,
                                json.dumps(["AAPL", "MSFT", "NVDA", "SPY"])))
        except sqlite3.IntegrityError:
            raise ValueError("That username is unavailable. Choose another or sign in.") from None
    return owner, recovery


def login(username, password, client="unknown", now=None):
    stamp = int(time.time() if now is None else now)
    username = username.strip().lower()[:128]
    _limit("login", username, client, stamp)
    with database() as connection:
        user = connection.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    try:
        valid = _verify_secret(user["password_hash"] if user else DUMMY_HASH, str(password)[:129])
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or not user:
        raise ValueError("Username or password is incorrect.")
    token = secrets.token_urlsafe(32)
    with database() as connection, connection:
        connection.execute("DELETE FROM sessions WHERE expires_at<=?", (stamp,))
        connection.execute("INSERT INTO sessions VALUES (?, ?, ?)", (_digest(token), user["id"], stamp + 43200))
    return token


def principal(token, now=None):
    if not isinstance(token, str) or len(token) > 128:
        return None
    with database() as connection:
        row = connection.execute("""SELECT u.id,u.username,u.watchlist FROM sessions s JOIN users u ON u.id=s.owner
            WHERE s.token_hash=? AND s.expires_at>?""", (_digest(token), int(time.time() if now is None else now))).fetchone()
    return dict(row) if row else None


def logout(token):
    with database() as connection, connection:
        connection.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))


def recover(username, recovery, password, client="unknown", now=None):
    _password(password)
    username = username.strip().lower()[:128]
    _limit("recover", username, client, int(time.time() if now is None else now))
    with database() as connection:
        row = connection.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    try:
        valid = _verify_secret(row["recovery_hash"] if row else DUMMY_HASH, str(recovery)[:129])
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or not row:
        raise ValueError("Username or recovery code is incorrect.")
    replacement = secrets.token_urlsafe(32)
    with database() as connection, connection:
        # Prevent two concurrent uses of a one-time recovery code.
        cursor = connection.execute("UPDATE users SET password_hash=?,recovery_hash=? WHERE id=? AND recovery_hash=?",
                                    (_hash_secret(password), _hash_secret(replacement), row["id"], row["recovery_hash"]))
        if cursor.rowcount != 1:
            raise ValueError("Recovery code has already been used.")
        connection.execute("DELETE FROM sessions WHERE owner=?", (row["id"],))
    return replacement


def save_watchlist(owner, symbols):
    symbols = list(dict.fromkeys(symbols))
    if len(symbols) > 20 or any(not re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,11}", item) for item in symbols):
        raise ValueError("Keep at most 20 valid symbols in your watchlist.")
    with database() as connection, connection:
        connection.execute("UPDATE users SET watchlist=? WHERE id=?", (json.dumps(symbols), owner))


def save_feedback(owner, category, message, now=None):
    if category not in ("Bug", "Idea", "Data issue") or not 10 <= len(message.strip()) <= 3000:
        raise ValueError("Enter 10–3000 characters of feedback.")
    stamp = int(time.time() if now is None else now)
    with database() as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone():
            raise ValueError("Sign in to send feedback.")
        count = connection.execute("SELECT count(*) FROM feedback WHERE owner=? AND created_at>?", (owner, stamp - 3600)).fetchone()[0]
        if count >= 10:
            raise ValueError("Please wait before sending more feedback.")
        connection.execute("INSERT INTO feedback(owner,category,message,created_at) VALUES (?, ?, ?, ?)",
                           (owner, category, message.strip(), stamp))


def verify_password(owner, password):
    with database() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (owner,)).fetchone()
    try:
        valid = bool(row) and _verify_secret(row["password_hash"], password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid:
        raise ValueError("Password is incorrect.")


def delete_account(owner, password):
    verify_password(owner, password)
    with database() as connection, connection:
        connection.execute("DELETE FROM sessions WHERE owner=?", (owner,))
        connection.execute("DELETE FROM feedback WHERE owner=?", (owner,))
        connection.execute("DELETE FROM users WHERE id=?", (owner,))


def budget(bucket, maximum, window=60, now=None):
    stamp = int(time.time() if now is None else now)
    with database() as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM attempts WHERE at<?", (stamp - 86400,))
        count = connection.execute("SELECT count(*) FROM attempts WHERE bucket=? AND at>?", (bucket, stamp - window)).fetchone()[0]
        if count >= maximum:
            raise ValueError("The beta is busy. Please wait a minute and try again.")
        connection.execute("INSERT INTO attempts VALUES (?, ?)", (bucket, stamp))
