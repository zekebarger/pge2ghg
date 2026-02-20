import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import WattTimeRecord

logger = logging.getLogger(__name__)

# WattTime API limits historical requests to 32 days per call
MAX_CHUNK_DAYS = 32

# Module-level token cache: (token_string, expiry_datetime)
_token: str | None = None
_token_expiry: datetime | None = None
# Use a 29-minute lifetime to stay safely inside the 30-minute window
TOKEN_LIFETIME = timedelta(minutes=29)

# Sliding-window rate limiter settings (WattTime free tier: 10 req/s)
RATE_LIMIT_CALLS = 10   # max calls per window
RATE_LIMIT_WINDOW = 1.0  # seconds

# WattTime returns 5-minute data; PG&E intervals are 15-minute aligned,
# so we only cache and match on 15-minute-aligned points.
INTENSITY_INTERVAL_MINUTES = 15
INTENSITY_INTERVAL_SECONDS = INTENSITY_INTERVAL_MINUTES * 60  # 900


def get_token() -> str:
    """Return a valid bearer token, reusing the cached one if it hasn't expired."""
    global _token, _token_expiry
    if _token is not None and _token_expiry is not None and datetime.now(timezone.utc) < _token_expiry:
        return _token

    logger.info("Fetching new WattTime token")
    username = os.environ["WATTTIME_USER"]
    password = os.environ["WATTTIME_PASS"]
    rsp = requests.get(
        "https://api.watttime.org/login",
        auth=HTTPBasicAuth(username, password),
    )
    rsp.raise_for_status()
    _token = rsp.json()["token"]
    _token_expiry = datetime.now(timezone.utc) + TOKEN_LIFETIME
    return _token


REGION = "CAISO_NORTH"

# Sliding-window rate limiter: tracks the monotonic timestamps of the last
# RATE_LIMIT_CALLS get_historical calls. When the window is full, we sleep
# until the oldest call is more than RATE_LIMIT_WINDOW seconds old.
_call_times: deque[float] = deque(maxlen=RATE_LIMIT_CALLS)


def get_historical(start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch marginal CO2 intensity from WattTime for a date range (≤32 days)."""
    if len(_call_times) == RATE_LIMIT_CALLS:
        wait = RATE_LIMIT_WINDOW - (time.monotonic() - _call_times[0])
        if wait > 0:
            time.sleep(wait)
    _call_times.append(time.monotonic())

    logger.info("Fetching WattTime historical data: %s to %s", start, end)
    token = get_token()
    url = "https://api.watttime.org/v3/historical"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "region": REGION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "signal_type": "co2_moer",
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    df = pd.DataFrame.from_dict(response.json()["data"])
    # columns: point_time (ISO timestamp string), value (lbs CO2/MWh)
    return df


def fetch_and_store_intensity(db: Session, start_dt: datetime, end_dt: datetime) -> None:
    """
    Ensure WattTime intensity records for [start_dt, end_dt] are in the DB.

    Queries for existing rows first; only fetches from the API for sub-ranges
    that aren't already cached. Inserts use ON CONFLICT DO NOTHING so overlapping
    fetches are safe.
    """
    # Find which 15-min point_times we already have in the DB for this range
    existing_times = {
        row.point_time
        for row in db.query(WattTimeRecord.point_time)
        .filter(
            WattTimeRecord.point_time >= start_dt,
            WattTimeRecord.point_time <= end_dt,
        )
        .all()
    }

    # Walk the range in ≤32-day chunks, skipping any that are fully cached.
    chunk_start = start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(days=MAX_CHUNK_DAYS), end_dt)

        expected_slots = int((chunk_end - chunk_start).total_seconds() / INTENSITY_INTERVAL_SECONDS)
        chunk_existing = sum(1 for t in existing_times if chunk_start <= t <= chunk_end)
        if chunk_existing >= expected_slots:
            logger.info("Cache hit for chunk %s to %s, skipping API call", chunk_start, chunk_end)
            chunk_start = chunk_end
            continue

        df = get_historical(chunk_start, chunk_end)

        if df.empty:
            chunk_start = chunk_end
            continue

        # Keep only the 15-min-aligned points that PG&E intervals will actually use
        df["point_time"] = pd.to_datetime(df["point_time"], utc=True)
        df = df[df["point_time"].dt.minute % INTENSITY_INTERVAL_MINUTES == 0]

        # Bulk-insert with ON CONFLICT DO NOTHING to handle overlapping fetches
        rows = [
            {
                "point_time": row["point_time"],
                "value_lbs_per_mwh": row["value"],
                "fetched_at": datetime.now(timezone.utc),
            }
            for _, row in df.iterrows()
        ]
        stmt = insert(WattTimeRecord).values(rows).on_conflict_do_nothing(
            index_elements=["point_time"]
        )
        db.execute(stmt)
        db.commit()
        logger.info("Stored %d intensity rows for chunk %s to %s", len(rows), chunk_start, chunk_end)

        chunk_start = chunk_end
