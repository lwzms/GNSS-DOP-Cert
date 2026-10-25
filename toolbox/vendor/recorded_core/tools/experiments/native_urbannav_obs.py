"""Thin lexical/provenance adapter around the existing UrbanNav RINEX reader.

Only the reviewed RINEX 3.03 GPS-time path is supported. No historical measurement
table is opened by parse_native(); comparison is a separate, subsequent operation.
"""
from decimal import Decimal
import csv
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys

MODE = "NATIVE_RINEX_C1C_V1"
VERSION = "1.0"
TARGETS = [
    {"epoch_index": "0", "week": "2158", "tow_decimal": "95593.006", "gps_ns": "1305253993006000000"},
    {"epoch_index": "548", "week": "2158", "tow_decimal": "96141.006", "gps_ns": "1305254541006000000"},
    {"epoch_index": "785", "week": "2158", "tow_decimal": "96378.006", "gps_ns": "1305254778006000000"},
]


def parser_modules():
    source = Path(__file__).resolve().parents[2] / "src"
    sys.path.insert(0, str(source))
    reader = importlib.import_module("gnss_toolbox.data.staging.urbannav.rinex")
    header = importlib.import_module("gnss_toolbox.data.audit.rinex")
    modules = [importlib.import_module(name) for name in (
        "gnss_toolbox", "gnss_toolbox.data", "gnss_toolbox.data.audit",
        "gnss_toolbox.data.audit.timing", "gnss_toolbox.data.schema",
        "gnss_toolbox.data.staging", "gnss_toolbox.data.staging.urbannav")]
    for m in (reader, header, *modules):
        if not Path(m.__file__).resolve().is_relative_to(source):
            raise ValueError("PARSER_IMPORTED_FROM_OTHER_WORKSPACE")
    return reader, header


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(s):
    return Decimal(s.replace("D", "E").replace("d", "e"))


class RecordedPath:
    """Observe bytes read by the existing parser, without decoding observations."""
    def __init__(self, path):
        self.path, self.opens, self.blocks, self.header = path, 0, [], []

    def open(self, **kwargs):
        self.opens += 1
        if self.opens != 1:
            return self.path.open(**kwargs)
        return RecordedLines(self)


class RecordedLines:
    def __init__(self, owner):
        self.owner, self.handle, self.line, self.offset = owner, owner.path.open("rb"), 0, 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.handle.close()

    def __iter__(self):
        return self

    def __next__(self):
        raw = next(self.handle)
        self.line += 1
        item = {"line": self.line, "byte_offset": self.offset, "raw": raw}
        self.offset += len(raw)
        if raw.startswith(b">"):
            self.owner.blocks.append([])
        if self.owner.blocks:
            self.owner.blocks[-1].append(item)
        else:
            self.owner.header.append(item)
        return raw.decode("ascii")


def parse_native(path, selected, targets=TARGETS, *, allow_missing=False):
    """Return newly decoded rows plus original byte provenance; no old-table input."""
    if not path.is_file():
        raise ValueError("OBS_MISSING")
    reader, header_reader = parser_modules()
    with path.open(encoding="ascii") as h:
        header = header_reader.read_header(header_reader.Lines(h))
    clock_applied = header["fields"].get("RCV CLOCK OFFS APPL")
    if clock_applied and any(s.strip() not in ("0",) for s in clock_applied):
        raise ValueError("UNSUPPORTED_RECEIVER_CLOCK_HEADER")
    targets_by_ns = {int(t["gps_ns"]): t for t in targets}
    if len(targets_by_ns) != len(targets):
        raise ValueError("DUPLICATE_TARGET_TIME")
    grid_by_ns = {int(g["gps_ns"]): g for g in selected}
    if len(grid_by_ns) != len(selected) or set(grid_by_ns) != set(targets_by_ns):
        raise ValueError("TARGET_GRID_TIME_MISMATCH")
    for ns, t in targets_by_ns.items():
        g = grid_by_ns[ns]
        if any(g[k] != t[k] for k in ("epoch_index", "week", "tow_decimal", "gps_ns")):
            raise ValueError("TARGET_GRID_IDENTITY_MISMATCH")
        week, tow = divmod(ns, 604800_000000000)
        if week != int(t["week"]) or Decimal(tow) / 10**9 != number(t["tow_decimal"]):
            raise ValueError("INTERNAL_TARGET_TIME_MISMATCH")
    observed = RecordedPath(path)
    seen, raw, evidence, epochs = set(), {}, [], []
    count = 0
    for epoch, satellites in reader.observation_epochs(observed):
        count += 1
        ns = epoch.timestamp_ns
        if ns in seen:
            raise ValueError("DUPLICATE_OBS_TIME")
        seen.add(ns)
        if ns not in targets_by_ns:
            continue
        if epoch.receiver_clock_offset_s is not None:
            raise ValueError("UNSUPPORTED_EPOCH_RECEIVER_CLOCK_OFFSET")
        g = grid_by_ns[ns]
        block = observed.blocks[epoch.source_epoch_index]
        starts = [i for i, b in enumerate(block[1:], 1) if re.fullmatch(rb"[A-Z][ 0-9][0-9]", b["raw"][:3])]
        if len(starts) != len(satellites):
            raise ValueError("PROVENANCE_SATELLITE_COUNT_MISMATCH")
        epoch_info = {"epoch_index": g["epoch_index"], "gps_ns": str(ns), "week": g["week"], "tow_decimal": g["tow_decimal"],
                      "original_time_text": block[0]["raw"].decode("ascii").rstrip("\r\n"),
                      "source_epoch_index": epoch.source_epoch_index, "epoch_flag": epoch.epoch_flag,
                      "receiver_clock_offset_s": epoch.receiver_clock_offset_s, "line": block[0]["line"],
                      "byte_offset": block[0]["byte_offset"], "binary64_tow_hex": float(g["tow_decimal"]).hex()}
        epochs.append(epoch_info)
        rr = []
        for order, ((sv, cells), start) in enumerate(zip(satellites, starts)):
            if not sv.startswith("G"):
                continue
            c, d, s = [cells.get(code, (None, None, None)) for code in ("C1C", "D1C", "S1C")]
            valid = c[0] is not None and number(c[0]).is_finite() and number(c[0]) > 0
            row = {"window": g["window"], "epoch_index": g["epoch_index"], "satellite": sv,
                   "C1C_raw": c[0] or "", "D1C_raw": d[0] or "", "S1C_raw": s[0] or "",
                   "C1C_SSI": "" if c[2] is None else str(c[2]), "eligible": str(valid),
                   "reason": "positive raw GPS C1C" if valid else "missing/nonpositive C1C"}
            rr.append(row)
            end = starts[order+1] if order+1 < len(starts) else len(block)
            source_rows = block[start:end]
            evidence.append({**row, **epoch_info, "signal": "C1C", "original_satellite_order": order,
                             "gps_candidate_order": len(rr)-1, "satellite_line": source_rows[0]["line"],
                             "satellite_byte_offset": source_rows[0]["byte_offset"],
                             "continuation_lines": len(source_rows)-1, "C1C_LLI": c[1],
                             "original_records": [b["raw"].decode("ascii") for b in source_rows]})
        raw[g["epoch_index"]] = rr
    if len(raw) != len(targets) and not allow_missing:
        raise ValueError("TARGET_EPOCH_MISSING")
    provenance = {"mode": MODE, "adapter_version": VERSION, "obs_path": str(path), "obs_sha256": digest(path),
                  "parser_path": reader.__file__, "parser_sha256": digest(Path(reader.__file__)),
                  "header": header, "RCV_CLOCK_OFFS_APPL": clock_applied if clock_applied else "ABSENT",
                  "parsed_epoch_count": count, "selection": "exact integer GPS nanoseconds; no nearest matching",
                  "epochs": epochs, "measurements": evidence,
                  "original_header": [b["raw"].decode("ascii") for b in observed.header],
                  "screening": "finite positive C1C only; LLI/SSI/SNR do not reject code; no clock correction"}
    return raw, provenance


def compare_measurements(raw, historical_path, selected):
    """Open historical excerpt only after caller has saved the native outputs."""
    with historical_path.open(encoding="utf-8-sig", newline="") as h:
        old = list(csv.DictReader(h))
    differences, counts = [], []
    for g in selected:
        new = raw[g["epoch_index"]]
        expected = [r for r in old if r["epoch_index"] == g["epoch_index"]]
        if new != expected:
            differences.append({"epoch_index": g["epoch_index"], "native": new, "historical": expected})
        counts.append({"epoch_index": g["epoch_index"], "gps_ns": g["gps_ns"],
                       "candidate_satellites": [r["satellite"] for r in new],
                       "eligible_satellites": [r["satellite"] for r in new if r["eligible"] == "True"],
                       "all_cells_exact": new == expected})
    return {"all_equal": not differences, "differences": differences, "epochs": counts,
            "policy": "exact ordered lexical C1C/D1C/S1C/SSI, eligibility and reason; time checked against frozen grid",
            "history_read_after_native_outputs_sealed": True, "history_supplies_solver_values": False}
