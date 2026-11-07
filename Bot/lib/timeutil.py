from datetime import datetime, timezone


# The bot works with naive datetimes in UTC and stores them as unix timestamps.
# datetime.timestamp()/fromtimestamp() on naive values use the *machine* timezone,
# so always attach UTC explicitly: the stored values must not depend on the host.

def utcnow() -> datetime:
    """current time as a naive UTC datetime (datetime.utcnow() is deprecated)"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_timestamp(naive_utc: datetime) -> float:
    """unix timestamp of a naive UTC datetime"""
    return naive_utc.replace(tzinfo=timezone.utc).timestamp()


def utc_from_timestamp(timestamp: float) -> datetime:
    """naive UTC datetime of a unix timestamp"""
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)


def to_minute(dt: datetime) -> datetime:
    """dt without seconds and microseconds (None stays None)

    Repeating reminders work to the minute: a rule started at 20:15:27 would
    fire at 20:15:27, and an exception date typed as 20:15 would never match it
    """
    return dt.replace(second=0, microsecond=0) if dt else dt
