"""Exact timestamp parsing and descriptive timing statistics."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

NS = 1_000_000_000
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def seconds_to_ns(text: str) -> int:
    value = Decimal(text) * NS
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError("timestamp must be finite with at most nanosecond precision")
    return int(value)


def calendar_ns(parts: list[str]) -> int:
    """Encode native calendar fields; this function does not change time scales."""
    year, month, day, hour, minute = map(int, parts[:5])
    seconds = seconds_to_ns(parts[5])
    if not 0 <= seconds < 60 * NS:
        raise ValueError("leap-second/calendar-second handling needs an explicit policy")
    base = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    delta = base - UNIX_EPOCH
    return (delta.days * 86400 + delta.seconds) * NS + seconds


def gps_week_tow_to_unix_ns(week: int, tow: str, *, leap_seconds: int) -> int:
    """Configured GPS-UTC offset required; no current/future leap table inferred."""
    if type(week) is not int or week < 0 or type(leap_seconds) is not int:
        raise ValueError("week and leap offset must be explicit integers")
    ns = seconds_to_ns(tow)
    if not 0 <= ns < 604800 * NS:
        raise ValueError("time of week out of range")
    return (week * 604800 + 315964800 - leap_seconds) * NS + ns


def format_calendar(ns: int) -> str:
    seconds, fraction = divmod(ns, NS)
    return (UNIX_EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:09d}"


def percentile(values: list[int | float], q: float) -> float | None:
    if not 0 <= q <= 1:
        raise ValueError("quantile must be in [0,1]")
    if not values:
        return None
    ordered = sorted(values)
    point = (len(ordered) - 1) * q
    low = int(point)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (point - low)


def timing_summary(stamps: list[int], *, gap_factor: float = 1.5) -> dict:
    if not stamps or any(type(x) is not int for x in stamps):
        raise ValueError("nonempty integer timestamp sequence required")
    if gap_factor <= 1:
        raise ValueError("gap_factor must exceed one")
    diffs = [b - a for a, b in zip(stamps, stamps[1:])]
    positive = [d for d in diffs if d > 0]
    typical = median(positive) if positive else None
    counts = Counter(positive)
    max_count = max(counts.values(), default=0)
    modes = sorted(x for x, n in counts.items() if n == max_count)
    threshold = typical * gap_factor if typical is not None else None
    gaps = [{"before_ns": a, "after_ns": b, "duration_s": (b-a)/NS}
            for a, b in zip(stamps, stamps[1:]) if threshold is not None and b-a > threshold]
    return {
        "count": len(stamps), "first_ns": stamps[0], "last_ns": stamps[-1],
        "min_timestamp_ns": min(stamps), "max_timestamp_ns": max(stamps),
        "duration_s": (stamps[-1]-stamps[0])/NS,
        "duplicate_timestamps": len(stamps)-len(set(stamps)),
        "non_monotonic_steps": sum(d < 0 for d in diffs),
        "zero_dt_steps": sum(d == 0 for d in diffs),
        "min_dt_s": min(diffs)/NS if diffs else None,
        "max_dt_s": max(diffs)/NS if diffs else None,
        "median_positive_dt_s": typical/NS if typical is not None else None,
        "median_dt_s": median(diffs)/NS if diffs else None,
        "p01_dt_s": percentile(diffs, .01)/NS if diffs else None,
        "p50_dt_s": percentile(diffs, .50)/NS if diffs else None,
        "p99_dt_s": percentile(diffs, .99)/NS if diffs else None,
        "modal_positive_dt_s": modes[0]/NS if modes else None,
        "mode_tie_count": len(modes),
        "estimated_rate_hz": NS/typical if typical else None,
        "gap_factor": gap_factor, "gap_threshold_s": threshold/NS if threshold else None,
        "gap_count": len(gaps), "gaps": gaps,
        "largest_gaps": sorted(gaps, key=lambda g: g["duration_s"], reverse=True)[:20],
    }
