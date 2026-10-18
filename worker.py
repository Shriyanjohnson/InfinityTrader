"""Single-host daily alert inbox and payment reconciliation worker."""
from contextlib import contextmanager
import fcntl
import json
import logging
import os
import time

import accounts
from alerts import check_alerts, read_rules
from analytics import add_indicators
from billing import BlockstreamClient, check_payment, has_access, _database
from forecast_journal import settle_forecasts
from market_data import get_history
from settings import account_directory, checkout_enabled, data_root, free_beta, live_enabled

LOGGER = logging.getLogger("infinity.worker")


@contextmanager
def owner_lock(owner):
    account_directory(owner)  # Validate before constructing any filesystem path.
    folder = data_root() / "locks"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / f"{owner}.lock").open("a") as stream:
        os.chmod(stream.name, 0o600)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_once(loader=get_history):
    state = {"checked_at": int(time.time()), "accounts": 0, "symbols": 0, "matches": 0, "errors": 0,
             "live_enabled": live_enabled(), "checkout_enabled": checkout_enabled()}
    with accounts.database() as connection:
        connection.execute("DELETE FROM attempts WHERE at<?", (int(time.time()) - 86400,))
        connection.commit()
        users = [dict(row) for row in connection.execute("SELECT id,watchlist FROM users ORDER BY id")]
    targets = {}
    for user in users:
        owner = user["id"]
        with owner_lock(owner):
            with accounts.database() as connection:
                if not connection.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone():
                    continue
            state["accounts"] += 1
            if not live_enabled() or not (free_beta() or has_access(data_root() / "billing.sqlite3", owner)):
                continue
            directory = account_directory(owner)
            symbols = list(json.loads(user["watchlist"]))
            try:
                for name, query in [("alerts.sqlite3", "SELECT DISTINCT symbol FROM alert_rules WHERE enabled=1"),
                                    ("forecast_journal.sqlite3", "SELECT DISTINCT symbol FROM forecasts WHERE outcome IS NULL")]:
                    path = directory / name
                    if path.exists():
                        import sqlite3
                        with sqlite3.connect(path) as db:
                            symbols += [row[0] for row in db.execute(query)]
            except Exception:
                state["errors"] += 1
            for symbol in set(symbols):
                targets.setdefault(symbol, []).append(owner)
    symbols = sorted(targets)
    try:
        offset = int(json.loads((data_root() / "worker-status.json").read_text()).get("next_symbol", 0)) % max(1, len(symbols))
    except (OSError, ValueError, TypeError):
        offset = 0
    queue = (symbols[offset:] + symbols[:offset])[:100]
    state["queued_symbols"] = len(symbols)
    state["next_symbol"] = (offset + len(queue)) % max(1, len(symbols))
    for symbol in queue:
        try:
            data = add_indicators(loader(symbol))
            state["symbols"] += 1
        except Exception:
            state["errors"] += 1
            continue
        for owner in targets[symbol]:
            with owner_lock(owner):
                with accounts.database() as connection:
                    if not connection.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone():
                        continue
                if not (free_beta() or has_access(data_root() / "billing.sqlite3", owner)):
                    continue
                directory = account_directory(owner)
                try:
                    _, new = check_alerts(directory / "alerts.sqlite3", symbol, data)
                    settle_forecasts(directory / "forecast_journal.sqlite3", symbol, data)
                    state["matches"] += new
                except Exception:
                    state["errors"] += 1
    target = data_root() / "worker-status.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(target)
    return state


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    data_root().mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data_root() / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A worker is already running for this data directory.")
        while True:
            try:
                state = run_once()
                LOGGER.info("Worker cycle finished: symbols=%s errors=%s", state["symbols"], state["errors"])
            except Exception:
                LOGGER.error("Worker cycle failed; inspect configuration and storage.")
            if args.once:
                return
            time.sleep(max(60, int(os.environ.get("INFINITY_WORKER_INTERVAL", "900"))))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
