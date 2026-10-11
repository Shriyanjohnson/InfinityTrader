from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from billing import (BillingError, BlockchainUnavailable, BlockstreamClient, CONFIG,
                     check_payment, create_invoice, has_access)

NOW = 1_780_000_000
TXID = "a" * 64
ADDRESS = CONFIG["receiving_address"]
BLOCK_HASH = "b" * 64


class Chain:
    def __init__(self):
        self.height = 100
        self.mempool = []
        self.tx = {"txid": TXID, "vout": [{"scriptpubkey_address": ADDRESS, "value": 10000}],
                   "status": {"confirmed": False}}
        self.block_hash = BLOCK_HASH

    def tip_height(self):
        return self.height

    def unconfirmed_txids(self, address):
        return self.mempool

    def transaction(self, txid):
        return deepcopy(self.tx)

    def canonical_hash(self, height):
        return self.block_hash

    def confirm(self, *, height=101, timestamp=NOW + 30, confirmations=3):
        self.tx["status"] = dict(confirmed=True, block_height=height,
                                  block_time=timestamp, block_hash=BLOCK_HASH)
        self.height = height + confirmations - 1


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "billing.sqlite3"
        self.chain = Chain()
        self.invoice = create_invoice(self.database, "alice", 50000, self.chain, now=NOW)

    def check(self, **kwargs):
        return check_payment(self.database, self.invoice["id"], "alice", TXID,
                             self.chain, now=kwargs.pop("now", NOW + 60), **kwargs)

    def test_five_dollar_quote_and_purchase_window(self):
        self.assertEqual(self.invoice["amount_sats"], 10000)
        self.assertEqual(self.invoice["created_at"], NOW)
        self.assertEqual(self.invoice["expires_at"], NOW + 900)
        self.assertEqual(self.invoice["start_height"], 100)
        self.assertFalse(has_access(self.database, "alice", now=NOW))

    def test_owner_binding(self):
        with self.assertRaises(BillingError):
            check_payment(self.database, self.invoice["id"], "bob", TXID, self.chain, now=NOW + 30)

    def test_same_amount_cannot_overlap_on_static_address(self):
        with self.assertRaises(BillingError):
            create_invoice(self.database, "bob", 50000, self.chain, now=NOW + 30)

    def test_invalid_quote_rejected(self):
        for rate in [0, -1, "NaN", "Infinity", "not-a-rate"]:
            with self.subTest(rate=rate), self.assertRaises(BillingError):
                create_invoice(self.database, "bob", rate, self.chain, now=NOW + 30)

    def test_unconfirmed_payment_never_grants_access(self):
        result = self.check()
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertEqual(result.confirmations, 0)
        self.assertFalse(has_access(self.database, "alice", now=NOW + 60))

    def test_three_confirmations_required(self):
        self.chain.confirm(confirmations=2)
        self.assertEqual(self.check().confirmations, 2)
        self.assertFalse(has_access(self.database, "alice", now=NOW + 60))
        self.chain.height += 1
        result = self.check()
        self.assertEqual(result.status, "paid")
        self.assertEqual(result.access_until, NOW + 60 + 30 * 86400)
        self.assertTrue(has_access(self.database, "alice", now=result.access_until - 1))
        self.assertFalse(has_access(self.database, "alice", now=result.access_until))

    def test_wrong_recipient_or_amount_rejected(self):
        for address, amount in [("other-address", 10000), (ADDRESS, 9999), (ADDRESS, 10001)]:
            with self.subTest(address=address, amount=amount):
                self.chain.tx["vout"] = [{"scriptpubkey_address": address, "value": amount}]
                self.chain.confirm()
                with self.assertRaises(BillingError):
                    self.check()
                self.assertFalse(has_access(self.database, "alice", now=NOW + 60))

    def test_preexisting_confirmed_payment_rejected(self):
        for height, timestamp in [(100, NOW + 10), (101, NOW - 1)]:
            with self.subTest(height=height, timestamp=timestamp):
                self.chain.confirm(height=height, timestamp=timestamp)
                with self.assertRaises(BillingError):
                    self.check()

    def test_preexisting_mempool_payment_rejected(self):
        self.chain.mempool = [TXID]
        invoice = create_invoice(self.database, "bob", 40000, self.chain, now=NOW + 1)
        self.chain.tx["vout"][0]["value"] = 12500
        with self.assertRaises(BillingError):
            check_payment(self.database, invoice["id"], "bob", TXID, self.chain, now=NOW + 20)

    def test_late_unseen_payment_expires(self):
        self.assertEqual(self.check(now=NOW + 901).status, "expired")
        self.chain.confirm(timestamp=NOW + 901)
        self.assertEqual(self.check(now=NOW + 1000).status, "expired")
        self.assertFalse(has_access(self.database, "alice", now=NOW + 1000))

    def test_payment_observed_in_window_can_confirm_after_expiry(self):
        self.check(now=NOW + 100)
        self.chain.confirm(timestamp=NOW + 1800)
        result = self.check(now=NOW + 1900)
        self.assertEqual(result.status, "paid")
        self.assertEqual(result.access_until, NOW + 1900 + 30 * 86400)

    def test_payment_mined_in_window_can_be_checked_later(self):
        self.chain.confirm(timestamp=NOW + 100)
        self.assertEqual(self.check(now=NOW + 2000).status, "paid")

    def test_reorganized_block_never_grants_access(self):
        self.chain.confirm()
        self.chain.block_hash = "c" * 64
        self.assertEqual(self.check().status, "awaiting_confirmation")
        self.assertFalse(has_access(self.database, "alice", now=NOW + 60))

    def test_retries_and_concurrent_checks_grant_exactly_once(self):
        self.chain.confirm()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.check(), range(2)))
        self.assertEqual(results[0].access_until, results[1].access_until)
        self.assertEqual(self.check(now=NOW + 600).access_until, results[0].access_until)
        self.assertFalse(has_access(self.database, "alice", now=results[0].access_until))

    def test_transaction_cannot_pay_for_another_purchase(self):
        self.chain.confirm()
        self.check()
        invoice = create_invoice(self.database, "bob", 50000, self.chain, now=NOW + 70)
        with self.assertRaises(BillingError):
            check_payment(self.database, invoice["id"], "bob", TXID, self.chain, now=NOW + 100)

    def test_renewal_adds_thirty_days_to_existing_access(self):
        self.chain.confirm()
        first = self.check()
        invoice = create_invoice(self.database, "alice", 50000, self.chain, now=NOW + 70)
        second_id = "d" * 64
        self.chain.tx["txid"] = second_id
        self.chain.confirm(height=104, timestamp=NOW + 80)
        result = check_payment(self.database, invoice["id"], "alice", second_id, self.chain, now=NOW + 120)
        self.assertEqual(result.access_until, first.access_until + 30 * 86400)

    def test_invalid_or_mismatched_transaction_id_rejected(self):
        with self.assertRaises(BillingError):
            check_payment(self.database, self.invoice["id"], "alice", "../bad", self.chain, now=NOW + 60)
        self.chain.tx["txid"] = "f" * 64
        with self.assertRaises(BlockchainUnavailable):
            self.check()

    def test_api_failure_leaves_access_locked(self):
        self.chain.transaction = Mock(side_effect=BlockchainUnavailable("offline"))
        with self.assertRaises(BlockchainUnavailable):
            self.check()
        self.assertFalse(has_access(self.database, "alice", now=NOW + 60))


class BlockchainClientTests(unittest.TestCase):
    def test_api_failure_uses_tls_timeouts_and_safe_error(self):
        import requests
        client = BlockstreamClient()
        client.session = Mock()
        client.session.get.side_effect = requests.Timeout()
        with self.assertRaises(BlockchainUnavailable):
            client.tip_height()
        args, kwargs = client.session.get.call_args
        self.assertTrue(args[0].startswith("https://"))
        self.assertGreater(kwargs["timeout"], 0)
        self.assertNotEqual(kwargs.get("verify"), False)
        client._get = Mock(return_value="-1")
        with self.assertRaises(BlockchainUnavailable):
            client.tip_height()
        client._get = Mock(return_value="invalid-hash")
        with self.assertRaises(BlockchainUnavailable):
            client.canonical_hash(100)

    def test_incomplete_mempool_snapshot_blocks_invoice_creation(self):
        client = BlockstreamClient()
        for rows in [[{"txid": str(i)} for i in range(50)], [{}], [{"txid": 42}]]:
            with self.subTest(rows=rows):
                client._get = Mock(return_value=rows)
                with self.assertRaises(BlockchainUnavailable):
                    client.unconfirmed_txids(ADDRESS)
