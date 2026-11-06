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
