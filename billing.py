"""Purchase-linked Bitcoin verification. Call only with a trusted signed-in user ID.

Authentication is provided by accounts.py; checkout and reconciliation call this
module with server-verified account IDs. It accepts no private keys and sends no funds.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

import requests

CONFIG = json.loads(Path(__file__).with_name("billing_config.json").read_text())


class BillingError(ValueError):
    pass


class BlockchainUnavailable(RuntimeError):
    pass


class BlockstreamClient:
    """Obtain transaction and canonical-chain data server-side, over verified TLS."""
    def __init__(self, base_url=CONFIG["blockchain_api_url"]):
        if not base_url.startswith("https://"):
            raise ValueError("Blockchain API requires HTTPS.")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _get(self, path, *, as_json=False):
        try:
            response = self.session.get(self.base_url + path, timeout=12)
            response.raise_for_status()
            return response.json() if as_json else response.text.strip()
        except (requests.RequestException, ValueError) as error:
            raise BlockchainUnavailable("Blockchain lookup is unavailable; access has not been granted.") from error

    def tip_height(self):
        try:
            height = int(self._get("/blocks/tip/height"))
            if height < 0:
                raise ValueError
            return height
        except ValueError as error:
            raise BlockchainUnavailable("Invalid chain-height response.") from error

    def transaction(self, txid):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", txid):
            raise BillingError("Enter a valid transaction ID.")
        return self._get(f"/tx/{txid.lower()}", as_json=True)

    def canonical_hash(self, height):
        block_hash = self._get(f"/block-height/{int(height)}")
        if not re.fullmatch(r"[a-f0-9]{64}", block_hash):
            raise BlockchainUnavailable("Invalid canonical block response.")
        return block_hash

    def unconfirmed_txids(self, address):
        if not re.fullmatch(r"[a-zA-Z0-9]{26,90}", address):
            raise BillingError("Invalid receiving address.")
        rows = self._get(f"/address/{address}/txs/mempool", as_json=True)
        # Esplora's address mempool response is limited to 50 transactions.
        if not isinstance(rows, list) or len(rows) >= 50:
            raise BlockchainUnavailable("Cannot establish a complete prior-payment snapshot.")
        txids = []
        for row in rows:
            txid = row.get("txid") if isinstance(row, dict) else None
            if not isinstance(txid, str) or not re.fullmatch(r"[a-f0-9]{64}", txid):
                raise BlockchainUnavailable("Invalid prior-payment snapshot.")
            txids.append(txid)
        return txids

    def address_transactions(self, address):
        if not re.fullmatch(r"[a-zA-Z0-9]{26,90}", address):
            raise BillingError("Invalid receiving address.")
        rows = self._get(f"/address/{address}/txs", as_json=True)
        if not isinstance(rows, list) or len(rows) > 100:
            raise BlockchainUnavailable("Invalid address transaction response.")
        return rows


@contextmanager
def _database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, address TEXT NOT NULL,
          amount_sats INTEGER NOT NULL, created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL, start_height INTEGER NOT NULL,
          prior_mempool TEXT NOT NULL, observed_txid TEXT, first_seen_at INTEGER,
          paid_txid TEXT UNIQUE, paid_at INTEGER, access_until INTEGER);
        CREATE TABLE IF NOT EXISTS entitlements (
          owner TEXT PRIMARY KEY, access_until INTEGER NOT NULL);
        """)
        path.chmod(0o600)
        yield connection
    finally:
        connection.close()


def create_invoice(database, authenticated_user_id, usd_per_btc, chain, *, now=None):
    """Use a server-obtained exchange rate, never a rate or user ID from form input."""
    if not authenticated_user_id:
        raise BillingError("A signed-in account is required.")
    try:
        rate = Decimal(str(usd_per_btc))
        if not rate.is_finite() or rate <= 0:
            raise ValueError
        sats = int((Decimal(str(CONFIG["pro_price_usd"])) * 100_000_000 / rate).to_integral_value(rounding=ROUND_CEILING))
        if not 1 <= sats <= 2_100_000_000_000_000:
            raise ValueError
    except (ValueError, ArithmeticError):
        raise BillingError("A valid server-side BTC/USD quote is required.") from None
    address = CONFIG["receiving_address"]
    start_height = chain.tip_height()
    prior_mempool = chain.unconfirmed_txids(address)
    created_at = int(time.time() if now is None else now)
    invoice = dict(id=secrets.token_urlsafe(24), owner=authenticated_user_id,
        address=address, amount_sats=sats, created_at=created_at,
        expires_at=created_at + CONFIG["invoice_expiry_minutes"] * 60,
        start_height=start_height, prior_mempool=json.dumps(prior_mempool))
    with _database(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Do not invent a surcharge to make amounts unique. Serialize matching
        # amounts on the static address, including observed payments awaiting settlement.
        collision = connection.execute("""SELECT 1 FROM invoices WHERE address=? AND amount_sats=?
          AND paid_txid IS NULL AND (expires_at>? OR observed_txid IS NOT NULL)""",
          (address, sats, created_at)).fetchone()
        if collision:
            raise BillingError("Another purchase has reserved this BTC amount. Try again later.")
        connection.execute("""INSERT INTO invoices
          (id,owner,address,amount_sats,created_at,expires_at,start_height,prior_mempool)
          VALUES (:id,:owner,:address,:amount_sats,:created_at,:expires_at,:start_height,:prior_mempool)""", invoice)
        connection.commit()
    invoice.pop("prior_mempool")
    return invoice


@dataclass
class PaymentResult:
    status: str
    confirmations: int = 0
    access_until: int | None = None


def check_payment(database, invoice_id, authenticated_user_id, txid, chain, *, now=None):
    """Never trust a browser's amount, recipient, timestamp, or confirmation count."""
    checked_at = int(time.time() if now is None else now)
    if not isinstance(txid, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", txid):
        raise BillingError("Enter a valid transaction ID.")
    txid = txid.lower()
    with _database(database) as connection:
        invoice = connection.execute("SELECT * FROM invoices WHERE id=? AND owner=?",
                                     (invoice_id, authenticated_user_id)).fetchone()
        if invoice is None:
            raise BillingError("Purchase not found for this account.")
        invoice = dict(invoice)
        if invoice["paid_txid"]:
            return PaymentResult("paid", access_until=invoice["access_until"])
        used = connection.execute("SELECT id FROM invoices WHERE paid_txid=?", (txid,)).fetchone()
        if used:
            raise BillingError("This transaction has already paid for a purchase.")
    if txid in json.loads(invoice["prior_mempool"]):
        raise BillingError("This payment existed before the purchase was created.")
    if invoice["observed_txid"] and invoice["observed_txid"] != txid:
        raise BillingError("A different transaction is already awaiting confirmation for this purchase.")
    transaction = chain.transaction(txid)
    response_id = transaction.get("txid") if isinstance(transaction, dict) else None
    if not isinstance(response_id, str) or response_id.lower() != txid:
        raise BlockchainUnavailable("Transaction identity could not be verified.")
    outputs = transaction.get("vout")
    status = transaction.get("status")
    if not isinstance(outputs, list) or not isinstance(status, dict):
        raise BlockchainUnavailable("Incomplete blockchain transaction response.")
    if any(not isinstance(output, dict) for output in outputs):
        raise BlockchainUnavailable("Malformed blockchain transaction outputs.")
    matching = [output.get("value") for output in outputs if output.get("scriptpubkey_address") == invoice["address"]]
    if not matching or any(type(value) is not int or value < 0 for value in matching):
        raise BillingError("The transaction does not pay the receiving address.")
    if sum(matching) != invoice["amount_sats"]:
        raise BillingError("The received BTC amount does not match the purchase quote.")
    confirmations = 0
    if status.get("confirmed") is True:
        height, timestamp, block_hash = status.get("block_height"), status.get("block_time"), status.get("block_hash")
        if type(height) is not int or type(timestamp) is not int or not isinstance(block_hash, str):
            raise BlockchainUnavailable("Incomplete confirmation response.")
        if height <= invoice["start_height"] or timestamp < invoice["created_at"]:
            raise BillingError("This confirmed payment predates the purchase.")
        if timestamp > checked_at:
            return PaymentResult("awaiting_confirmation")
        observed_on_time = (invoice["observed_txid"] == txid and invoice["first_seen_at"] is not None
                            and invoice["first_seen_at"] <= invoice["expires_at"])
        if timestamp > invoice["expires_at"] and not observed_on_time:
            return PaymentResult("expired")
        if chain.canonical_hash(height) != block_hash:
            return PaymentResult("awaiting_confirmation")
        confirmations = max(0, chain.tip_height() - height + 1)
    elif status.get("confirmed") is False:
        if checked_at > invoice["expires_at"] and not invoice["first_seen_at"]:
            return PaymentResult("expired")
    else:
        raise BlockchainUnavailable("Confirmation status could not be verified.")
    with _database(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Recheck under the write lock: concurrent retries must never extend access twice.
        current = connection.execute("SELECT * FROM invoices WHERE id=? AND owner=?",
                                     (invoice_id, authenticated_user_id)).fetchone()
        if current["paid_txid"]:
            return PaymentResult("paid", access_until=current["access_until"])
        if connection.execute("SELECT 1 FROM invoices WHERE paid_txid=?", (txid,)).fetchone():
            raise BillingError("This transaction has already paid for a purchase.")
        if current["observed_txid"] and current["observed_txid"] != txid:
            raise BillingError("A different transaction is already awaiting confirmation.")
        # A late first check may accept a transaction already mined inside the window,
        # but cannot manufacture an earlier mempool observation for a later block.
        if checked_at <= invoice["expires_at"] and not current["observed_txid"]:
            connection.execute("UPDATE invoices SET observed_txid=?,first_seen_at=? WHERE id=?",
                               (txid, checked_at, invoice_id))
        if confirmations < CONFIG["required_confirmations"]:
            connection.commit()
            return PaymentResult("awaiting_confirmation", confirmations)
        existing = connection.execute("SELECT access_until FROM entitlements WHERE owner=?",
                                      (authenticated_user_id,)).fetchone()
        access_until = max(checked_at, existing[0] if existing else 0) + CONFIG["access_period_days"] * 86400
        connection.execute("UPDATE invoices SET paid_txid=?,paid_at=?,access_until=? WHERE id=?",
                           (txid, checked_at, access_until, invoice_id))
        connection.execute("""INSERT INTO entitlements(owner,access_until) VALUES (?,?)
          ON CONFLICT(owner) DO UPDATE SET access_until=excluded.access_until""",
          (authenticated_user_id, access_until))
        connection.commit()
        return PaymentResult("paid", confirmations, access_until)


def has_access(database, authenticated_user_id, *, now=None):
    checked_at = int(time.time() if now is None else now)
    with _database(database) as connection:
        row = connection.execute("SELECT access_until FROM entitlements WHERE owner=?",
                                 (authenticated_user_id,)).fetchone()
        return bool(row and row[0] > checked_at)
