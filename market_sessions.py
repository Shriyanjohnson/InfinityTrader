"""US regular-session boundaries, including exchange holidays and exceptional closures."""
from functools import lru_cache

import exchange_calendars as calendars
import pandas as pd


@lru_cache(maxsize=16)
def _calendar(year):
    return calendars.get_calendar("XNYS", start=f"{year - 1}-01-01", end=f"{year + 2}-12-31")


@lru_cache(maxsize=4096)
def next_session_info(source_session):
    """Return the next exchange session date and its UTC opening timestamp."""
    day = pd.Timestamp(source_session)
    calendar = _calendar(day.year)
    if not calendar.is_session(day):
        return None
    target = calendar.next_session(day)
    return target.date().isoformat(), calendar.session_open(target)


def session_matches(source_session, target_session):
    if pd.isna(source_session) or pd.isna(target_session):
        return False
    expected = next_session_info(source_session)
    return expected is not None and expected[0] == target_session
