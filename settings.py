"""Shared release settings and private storage paths."""
import os
from pathlib import Path
import re

VERSION = "1.0.0-beta.1"


def development():
    return os.environ.get("INFINITY_MODE", "beta") == "development"


def data_root():
    return Path(os.environ.get("INFINITY_DATA_DIR", Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "infinitytrader"))


def account_directory(owner):
    if not isinstance(owner, str) or not re.fullmatch(r"[a-f0-9]{32}", owner):
        raise ValueError("A verified account is required.")
    return data_root() / "users" / owner


def workspace_directory():
    if development():
        return data_root()
    import streamlit as st
    return account_directory(st.session_state.get("_principal", {}).get("id"))


def free_beta():
    return os.environ.get("INFINITY_FREE_BETA", "1") == "1"


def checkout_enabled():
    return os.environ.get("INFINITY_CHECKOUT_ENABLED", "0") == "1" and not free_beta()


def live_enabled():
    return development() or (os.environ.get("INFINITY_LIVE_DATA_ENABLED") == "1"
                             and os.environ.get("INFINITY_DATA_LICENSE_ACK") == "1")
