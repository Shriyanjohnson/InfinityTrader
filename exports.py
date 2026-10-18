"""Unique private downloads for Streamlit's content-addressed media storage."""
import secrets


def csv_bytes(frame, *, index=False):
    exported = frame.copy()
    # A random reference prevents guessing a private download's content hash
    # from predictable account fields or public market data. Original rows stay intact.
    exported["export_id"] = secrets.token_hex(32)
    return exported.to_csv(index=index).encode()
