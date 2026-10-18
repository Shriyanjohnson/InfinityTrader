"""Release preflight, private SQLite backups, and operator feedback export."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlparse

from settings import VERSION, checkout_enabled, data_root, development, live_enabled, free_beta


def preflight(public=False, online=False):
    checks = []
    def check(name, ready, detail):
        checks.append({"check": name, "ready": bool(ready), "detail": detail})
    root = data_root()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        import tempfile
        with tempfile.TemporaryFile(dir=root) as stream:
            stream.write(b"storage-check")
        writable = True
    except OSError:
        writable = False
    check("persistent_storage", writable, "A writable persistent data directory is required; back it up outside the app container.")
    check("mode", not public or not development(), "Public deployments must use INFINITY_MODE=beta.")
    if public:
        check("access_mode", free_beta() or checkout_enabled(), "Use free beta access or explicitly enable verified paid checkout before public signup.")
        url = urlparse(os.environ.get("INFINITY_PUBLIC_URL", ""))
        valid_url = (url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
                     and url.hostname not in ("localhost", "127.0.0.1", "beta.example.com", "example.com")
                     and not url.query and not url.fragment and url.path in ("", "/"))
        check("public_https_url", valid_url, "Set the actual INFINITY_PUBLIC_URL and configure DNS/HTTPS.")
        email = os.environ.get("INFINITY_SUPPORT_EMAIL", "")
        check("support_contact", bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)) and not email.endswith("@example.com"), "Set a monitored support/privacy address and publish retention/refund terms.")
        check("licensed_live_data", live_enabled() and os.environ.get("INFINITY_MARKET_PROVIDER", "twelvedata") == "twelvedata" and bool(os.environ.get("TWELVEDATA_API_KEY")), "Provide a Twelve Data plan/key permitting public display; set LIVE_DATA_ENABLED and DATA_LICENSE_ACK to 1.")
        check("operator_terms", os.environ.get("INFINITY_OPERATOR_TERMS_ACK") == "1", "Review the beta terms/privacy notice and adopt a 30-day backup-retention/refund policy before setting OPERATOR_TERMS_ACK=1.")
        check("storage_location", not root.resolve().is_relative_to(Path(__file__).parent.resolve()), "Keep account and payment databases outside the source checkout.")
    if online:
        if live_enabled():
            try:
                from analytics import add_indicators
                from market_data import get_history
                data = add_indicators(get_history("AAPL"))
                ready = len(data) >= 100
            except Exception:
                ready = False
            check("live_provider_request", ready, "A real adjusted AAPL history request must succeed.")
        if checkout_enabled():
            try:
                from billing import BlockstreamClient
                from checkout import btc_quote
                ready = BlockstreamClient().tip_height() > 0 and btc_quote() > 0
            except Exception:
                ready = False
            check("payment_services", ready, "Read-only chain height and fresh BTC/USD quote must succeed before charging.")
    return {"version": VERSION, "ready": all(row["ready"] for row in checks), "checks": checks}


def backup(destination):
    destination = Path(destination).resolve()
    root = data_root().resolve()
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("Choose a backup directory separate from the live data directory.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundle = destination / f"infinity-{time.time_ns()}"
    bundle.mkdir(mode=0o700)
    for path in root.rglob("*.sqlite3"):
        target = bundle / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source_db, target_db = sqlite3.connect(path), sqlite3.connect(target)
        try:
            source_db.backup(target_db)
            if target_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed.")
        finally:
            source_db.close()
            target_db.close()
        target.chmod(0o600)
    return bundle


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("preflight")
    ready.add_argument("--public", action="store_true")
    ready.add_argument("--online", action="store_true")
    save = sub.add_parser("backup")
    save.add_argument("destination")
    sub.add_parser("feedback")
    args = parser.parse_args()
    if args.command == "preflight":
        result = preflight(args.public, args.online)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["ready"] else 1)
    if args.command == "backup":
        print(backup(args.destination))
    if args.command == "feedback":
        import accounts
        with accounts.database() as connection:
            print(json.dumps([dict(row) for row in connection.execute("SELECT category,message,created_at FROM feedback ORDER BY id DESC LIMIT 200")], indent=2))


if __name__ == "__main__":
    main()
