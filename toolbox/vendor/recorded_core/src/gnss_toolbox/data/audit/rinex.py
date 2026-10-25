"""Restricted RINEX 3 observation inspector, never a measurement adapter.

Reject header-changing events and malformed/truncated records. Numeric fields are
counted for availability; only signal strength gets aggregate descriptive values.
"""

from collections import Counter, defaultdict
from math import isfinite
from pathlib import Path
import re

from .timing import calendar_ns, percentile, timing_summary

HEADER_LABELS = (
    "RINEX VERSION / TYPE", "MARKER NAME", "MARKER TYPE", "REC # / TYPE / VERS",
    "ANT # / TYPE", "APPROX POSITION XYZ", "ANTENNA: DELTA H/E/N", "INTERVAL",
    "TIME OF FIRST OBS", "TIME OF LAST OBS", "RCV CLOCK OFFS APPL",
    "GLONASS SLOT / FRQ #", "GLONASS COD/PHS/BIS", "SYS / PHASE SHIFT",
    "SIGNAL STRENGTH UNIT",
)


class Lines:
    def __init__(self, handle):
        self.handle = iter(handle)
        self.pending = None

    def pop(self):
        if self.pending is not None:
            value, self.pending = self.pending, None
            return value
        return next(self.handle, None)

    def peek(self):
        if self.pending is None:
            self.pending = next(self.handle, None)
        return self.pending


def read_header(lines: Lines) -> dict:
    fields = defaultdict(list)
    codes = defaultdict(list)
    expected = {}
    system = None
    while (line := lines.pop()) is not None:
        label = line[60:].strip()
        if label == "END OF HEADER":
            break
        if label in HEADER_LABELS:
            fields[label].append(line[:60].rstrip())
        if label == "SYS / # / OBS TYPES":
            if line[0].strip():
                system = line[0]
                expected[system] = int(line[3:6])
            if system is None:
                raise ValueError("observation continuation without a system")
            codes[system].extend(line[7:60].split())
    else:
        raise ValueError("missing END OF HEADER")
    first = fields.get("RINEX VERSION / TYPE", [""])[0]
    if not first.strip().startswith("3.") or "OBSERVATION DATA" not in first:
        raise ValueError("only RINEX 3 observation files are supported")
    if not expected or any(len(codes[s]) != n for s, n in expected.items()):
        raise ValueError("incomplete SYS / # / OBS TYPES")
    for items in codes.values():
        if len(set(items)) != len(items) or any(not re.fullmatch(r"[CLDS][1-9][A-Z]", c) for c in items):
            raise ValueError("invalid/duplicate observable codes")
    return {"version": first[:9].strip(), "fields": dict(fields), "observable_codes": dict(codes)}


def read_satellite(lines: Lines, observable_codes: dict) -> tuple[str, str]:
    """Shared bounded lexical reader; return normalized SV and raw field payload."""
    row = lines.pop()
    if row is None or not re.fullmatch(r"[A-Z][ 0-9][0-9]", row[:3]):
        raise ValueError("missing/invalid satellite row")
    sv = row[0] + f"{int(row[1:3]):02d}"
    if row[0] not in observable_codes:
        raise ValueError("satellite system absent from header")
    width = 16 * len(observable_codes[row[0]])
    payload = row[3:].rstrip("\r\n")
    while len(payload) < width and lines.peek() is not None and lines.peek().startswith("   "):
        payload = payload.ljust(((len(payload) + 15) // 16) * 16)
        payload += lines.pop()[3:].rstrip("\r\n")
    if len(payload) > width and payload[width:].strip():
        raise ValueError("extra satellite fields beyond header declaration")
    return sv, payload.ljust(width)


def inspect_observation(path: Path) -> dict:
    stamps, satellite_counts, epoch_presence = [], [], Counter()
    satellites = defaultdict(set)
    denominators, nonempty, nonfinite = Counter(), Counter(), Counter()
    strengths = defaultdict(list)
    flags, events = Counter(), Counter()
    epoch_rows = []
    with path.open(encoding="ascii") as handle:
        lines = Lines(handle)
        header = read_header(lines)
        for system, codes in header["observable_codes"].items():
            for code in codes:
                denominators[system + ":" + code] = 0
        while (line := lines.pop()) is not None:
            if not line.strip():
                continue
            if not line.startswith(">"):
                raise ValueError("expected epoch marker")
            parts = line[1:].split()
            if len(parts) < 8:
                raise ValueError("incomplete epoch record")
            stamp = calendar_ns(parts[:6])
            flag, count = int(parts[6]), int(parts[7])
            if count < 0:
                raise ValueError("negative record count")
            if flag not in (0, 1):
                if flag not in (2, 3, 5):
                    raise ValueError("header updates/cycle-slip records require a later adapter")
                events[flag] += 1
                for _ in range(count):
                    if lines.pop() is None:
                        raise ValueError("truncated event")
                continue
            flags[flag] += 1
            present = set()
            seen = set()
            for _ in range(count):
                sv, payload = read_satellite(lines, header["observable_codes"])
                system = sv[0]
                if sv in seen:
                    raise ValueError("duplicate satellite in an epoch")
                seen.add(sv)
                present.add(system)
                satellites[system].add(sv)
                if system not in header["observable_codes"]:
                    raise ValueError("satellite system absent from header")
                codes = header["observable_codes"][system]
                for index, code in enumerate(codes):
                    key = system + ":" + code
                    denominators[key] += 1
                    value = payload[index*16:index*16+14].strip()
                    if value:
                        number = float(value.replace("D", "E"))
                        nonempty[key] += 1
                        if not isfinite(number):
                            nonfinite[key] += 1
                        elif code.startswith("S"):
                            strengths[key].append(number)
            stamps.append(stamp)
            satellite_counts.append(count)
            epoch_presence.update(present)
            epoch_rows.append({"timestamp_ns": stamp, "satellite_count": count})
    timing = timing_summary(stamps)
    availability = {key: {"eligible_satellite_records": n, "nonempty": nonempty[key],
                          "nonempty_fraction": nonempty[key]/n if n else None, "nonfinite": nonfinite[key]}
                    for key, n in sorted(denominators.items())}
    cn0 = {key: {"count": len(v), "min": min(v), "max": max(v), "mean": sum(v)/len(v)}
           for key, v in sorted(strengths.items())}
    return {"header": header, "timing": timing, "epoch_flags": dict(flags), "events": dict(events),
            "satellites_per_epoch": {"min": min(satellite_counts), "max": max(satellite_counts),
                                     "p05": percentile(satellite_counts, .05),
                                     "p50": percentile(satellite_counts, .5),
                                     "p95": percentile(satellite_counts, .95)},
            "constellation_epoch_presence": dict(epoch_presence),
            "satellite_ids": {s: sorted(ids) for s, ids in satellites.items()},
            "availability": availability, "cn0": cn0, "epoch_rows": epoch_rows}
