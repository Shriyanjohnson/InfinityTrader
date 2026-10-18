"""Observe purchase-linked address transactions while browsers are closed."""
import logging
import re
import time

import accounts
from billing import (BlockstreamClient, BillingError, BlockchainUnavailable,
                     _database, check_payment)
from settings import checkout_enabled, data_root


def reconcile_once(chain=None, now=None):
    if not checkout_enabled():
        return {"checked": 0, "paid": 0, "errors": 0}
    stamp = int(time.time() if now is None else now)
    chain = chain or BlockstreamClient()
    result = {"checked": 0, "paid": 0, "errors": 0}
    with accounts.database() as connection:
        owners = {row[0] for row in connection.execute("SELECT id FROM users")}
    database = data_root() / "billing.sqlite3"
    with _database(database) as connection:
        invoices = [dict(row) for row in connection.execute("""SELECT * FROM invoices WHERE paid_txid IS NULL
            AND (expires_at>? OR observed_txid IS NOT NULL OR created_at>?) ORDER BY created_at LIMIT 200""", (stamp, stamp - 86400))]
    transactions = {}
    for invoice in invoices:
        if invoice["owner"] not in owners:
            continue
        try:
            if invoice["address"] not in transactions:
                transactions[invoice["address"]] = chain.address_transactions(invoice["address"])
            candidates = [invoice["observed_txid"]] if invoice["observed_txid"] else []
            for transaction in transactions[invoice["address"]]:
                if not isinstance(transaction, dict):
                    continue
                txid = transaction.get("txid")
                outputs = transaction.get("vout")
                if not isinstance(txid, str) or not re.fullmatch(r"[a-f0-9]{64}", txid) or not isinstance(outputs, list):
                    continue
                matching = [output.get("value") for output in outputs if isinstance(output, dict) and output.get("scriptpubkey_address") == invoice["address"]]
                if matching and all(type(value) is int and value >= 0 for value in matching) and sum(matching) == invoice["amount_sats"]:
                    candidates.append(txid)
            for txid in dict.fromkeys(candidates):
                try:
                    payment = check_payment(database, invoice["id"], invoice["owner"], txid, chain, now=stamp)
                    result["checked"] += 1
                    if payment.status == "paid":
                        result["paid"] += 1
                        break
                except BillingError:
                    continue
        except (BlockchainUnavailable, OSError):
            result["errors"] += 1
    return result


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            result = reconcile_once()
            if result["checked"] or result["errors"]:
                logging.info("Payment reconciliation: checked=%s errors=%s", result["checked"], result["errors"])
        except Exception:
            logging.error("Payment reconciliation unavailable; no access granted.")
        time.sleep(30)


if __name__ == "__main__":
    main()
