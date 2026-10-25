"""UrbanNav saved-P95 adapter: recheck qualifications, never run navigation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ADAPTER_ID = "URBANNAV_SAVED_P95_V1"
INPUT_MODE = "SAVED_P95_RECORDS_V1"
VERSION = "1.0"
COMPARISON_POLICY = "EXACT_DISCRETE_FLAGS_IDENTITY_CHECKS_REASONS_AND_COUNTS_V1"


class InputError(ValueError):
    pass


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    with path.open("x", encoding="utf8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def time_identity(row):
    try:
        week = int(row["week"])
        tow = Decimal(row["tow_decimal"])
        gps_ns = int(row["gps_ns"])
        if week < 0 or not tow.is_finite() or not 0 <= tow < 604800:
            raise ValueError("range")
        exact = Decimal(week * 604800 * 1_000_000_000) + tow * 1_000_000_000
        if exact != gps_ns:
            raise ValueError("encoding")
        return gps_ns
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise InputError("GPST_IDENTITY_MISMATCH") from exc


def grid_index(grid):
    by_index, by_time = {}, {}
    for r in grid:
        i, t = int(r["epoch_index"]), time_identity(r)
        if i in by_index or t in by_time:
            raise InputError("DUPLICATE_GRID_IDENTITY")
        by_index[i], by_time[t] = r, r
    return by_index


def bind_row(row, grid):
    i = int(row["epoch_index"])
    if i not in grid or row["window"] != grid[i]["window"]:
        raise InputError("GRID_WINDOW_OR_INDEX_MISMATCH")
    # Old raw/model CSVs omit GPST. Bind only through their pinned file version
    # plus this canonical grid/window/index, never through CSV row order.
    for k in ("gps_ns", "week", "tow_decimal"):
        if k in row and Decimal(str(row[k])) != Decimal(str(grid[i][k])):
            raise InputError("GRID_TIME_MISMATCH")
    if all(k in row for k in ("gps_ns", "week", "tow_decimal")):
        time_identity(row)
    return grid[i]


def load_module(path):
    spec = importlib.util.spec_from_file_location("e2_saved_qualification", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_preserved(protocol, directory):
    # Only the inputs actually used in this adapter; no historical all-file scan.
    names = {
        "baseline_A.json": "gnss_p95_01", "baseline_B.json": "gnss_p95_01",
        "raw_gps_fields.csv": "gnss_p95_01", "satellite_terms.csv": "gnss_p95_01",
        "grid.csv": "gnss_p95_01", "freeze.json": "gnss_p95_01",
        "audit_results.json": "gnss_p95_ref01",
    }
    for name, parent in names.items():
        key = f"results/research_review/{parent}/{name}"
        if key not in protocol["preserved"] or sha(directory / name) != protocol["preserved"][key]["sha256"]:
            raise InputError(f"PROTOCOL_INPUT_VERSION_MISMATCH: {name}")


def build_records(directory, module):
    protocol = load(directory / "protocol.json")
    module.validate_protocol(protocol)
    validate_preserved(protocol, directory)
    frozen = load(directory / "freeze.json")
    grid = grid_index(rows(directory / "grid.csv"))
    if sum(w["count"] for w in frozen["windows"]) != len(grid):
        raise InputError("FROZEN_GRID_COUNT_MISMATCH")
    for w in frozen["windows"]:
        members = [g for g in grid.values() if g["window"] == w["name"]]
        if len(members) != w["count"] or min(int(g["epoch_index"]) for g in members) != w["first_index"] or max(int(g["epoch_index"]) for g in members) != w["last_index"]:
            raise InputError("FROZEN_WINDOW_MISMATCH")
        if min(int(g["gps_ns"]) for g in members) != w["first_gps_ns"] or max(int(g["gps_ns"]) for g in members) != w["last_gps_ns"]:
            raise InputError("FROZEN_WINDOW_TIME_MISMATCH")
    dataset = "UrbanNav-HK-Medium-Urban-1/ublox.f9p.splitter/GPS-C1C/" + frozen["input"]["sha256"]
    raw, terms = defaultdict(list), defaultdict(list)
    raw_links, term_links = defaultdict(list), defaultdict(list)
    seen_raw, seen_terms = set(), set()
    for number, r in enumerate(rows(directory / "raw_gps_fields.csv"), 2):
        g = bind_row(r, grid)
        key = (dataset, int(g["gps_ns"]), r["satellite"])
        if key in seen_raw:
            raise InputError("DUPLICATE_OBSERVATION_IDENTITY")
        seen_raw.add(key)
        raw[int(g["gps_ns"])].append(r)
        raw_links[int(g["gps_ns"])].append(number)
    for number, r in enumerate(rows(directory / "satellite_terms.csv"), 2):
        g = bind_row(r, grid)
        if r["method"] not in ("A", "B"):
            raise InputError("UNSUPPORTED_METHOD")
        key = (dataset, r["method"], int(g["gps_ns"]), r["sv"])
        if key in seen_terms:
            raise InputError("DUPLICATE_MODEL_ROW_IDENTITY")
        seen_terms.add(key)
        epoch_key = (r["method"], int(g["gps_ns"]))
        terms[epoch_key].append(r)
        term_links[epoch_key].append(number)
    inputs = {p.name: {"sha256": sha(p), "size_bytes": p.stat().st_size} for p in sorted(directory.iterdir()) if p.is_file()}
    result, seen, baseline_by_key = [], set(), {}
    for method in ("A", "B"):
        baseline_name = f"baseline_{method}.json"
        for number, epoch in enumerate(load(directory / baseline_name)):
            g = bind_row(epoch, grid)
            if epoch["method"] != method:
                raise InputError("METHOD_IDENTITY_MISMATCH")
            key = (dataset, method, int(g["gps_ns"]))
            if key in seen:
                raise InputError("DUPLICATE_RESULT_IDENTITY")
            seen.add(key)
            t = int(g["gps_ns"])
            observations, model_rows = raw[t], terms[(method, t)]
            if any(module.truth(r["accepted"]) != module.truth(epoch["accepted"]) for r in model_rows):
                raise InputError("MODEL_SOFTWARE_IDENTITY_MISMATCH")
            eligible = [r["satellite"] for r in observations if module.truth(r["eligible"]) == module.T]
            if set(eligible) != set(epoch["input_satellites"]) or len(eligible) != epoch["input_count"]:
                raise InputError("OBSERVATION_SET_IDENTITY_MISMATCH")
            q = module.qualify_saved_epoch(epoch, observations, model_rows, protocol, time_valid=module.T)
            out = {"dataset_id": dataset, "method_id": method, "method": method, "window": epoch["window"],
                   "epoch_index": int(epoch["epoch_index"]), "gps_ns": epoch["gps_ns"], "week": epoch["week"],
                   "tow_decimal": epoch["tow_decimal"], "source_result_id": inputs[baseline_name]["sha256"] + f"#/{number}",
                   "protocol_id": protocol["protocol_id"], "protocol_sha256": inputs["protocol.json"]["sha256"],
                   "qualification_module_version": module.VERSION, "adapter_version": VERSION,
                   "solver_original_accepted": epoch["accepted"], "solver_converged": epoch["converged"],
                   "solver_failure_category": epoch["failure_category"], "solver_return_information": dict(epoch),
                   "model_validation_scope": module.MODEL_SCOPE, **q}
            out["source_evidence"] = {
                "baseline": {"file": baseline_name, "sha256": inputs[baseline_name]["sha256"], "json_pointer": f"/{number}"},
                "canonical_time_grid": {"file": "grid.csv", "sha256": inputs["grid.csv"]["sha256"], "key": {k: g[k] for k in g}},
                "observation_rows": {"file": "raw_gps_fields.csv", "sha256": inputs["raw_gps_fields.csv"]["sha256"], "csv_line_numbers": raw_links[t]},
                "model_rows": {"file": "satellite_terms.csv", "sha256": inputs["satellite_terms.csv"]["sha256"], "csv_line_numbers": term_links[(method, t)]},
                "protocol": {"file": "protocol.json", "sha256": inputs["protocol.json"]["sha256"], "source_rules": module.SOURCE_RULES},
                "reference_contract": {"protocol_pointer": "/reference", "audit_file": "audit_results.json", "sha256": inputs["audit_results.json"]["sha256"]},
                "final_atmosphere_domain": {"saved_height_m": epoch.get("model_height_m"), "saved_SAAS_out": epoch.get("SAAS_out"),
                    "height_interval_m": protocol["model_profile"]["height_m"],
                    "note": "finite zero trop_m does not establish in-domain validity; retain the separate height-domain check"},
                "binding_limit": "raw/model CSVs omit GPST; exact pinned versions plus canonical dataset/grid/window/index binding; not inferred row order",
                "check_sources": {"obs_checks": ["observation_rows", "canonical_time_grid"],
                                  "nav_checks": ["model_rows", "baseline", "protocol"],
                                  "model_checks": ["baseline", "model_rows", "observation_rows", "protocol"],
                                  "solver_checks": ["baseline"], "reference_checks": ["reference_contract"]},
            }
            result.append(out)
            baseline_by_key[key] = epoch
    expected = {(dataset, m, int(g["gps_ns"])) for m in ("A", "B") for g in grid.values()}
    if seen != expected:
        raise InputError("BASELINE_GRID_COVERAGE_MISMATCH")
    return result, protocol, inputs, baseline_by_key, grid


def summary(records, module):
    windows = {}
    for w in sorted({r["window"] for r in records}):
        windows[w] = {}
        for m in ("A", "B"):
            rr = [r for r in records if r["window"] == w and r["method"] == m]
            windows[w][m] = {"N_grid": len(rr), "final_state_counts": dict(Counter(r["FINAL_STATE"] for r in rr)),
                             "flags": {k: {v: sum(r[k] == v for r in rr) for v in (module.T, module.F, module.U)} for k in module.FLAGS},
                             "zero_redundancy_accepted_count": sum(r["SOLVER_VALID"] == module.T and r["fault_monitor_redundancy"] == module.F for r in rr)}
    return {"protocol_id": module.PROTOCOL_ID, "model_validation_scope": module.MODEL_SCOPE,
            "record_count": len(records), "common_time_count": len({(r["dataset_id"], r["gps_ns"]) for r in records}),
            "windows": windows, "new_solver_calls": 0, "ephemeris_propagation_calls": 0, "imu_integration_calls": 0,
            "P95_recomputed": False, "reference_qualified_P95": None,
            "reference_actual_eligibility_rate": None, "real_navigation_effective_ratio": None,
            "null_reason": "REFERENCE_UNKNOWN; no newly certified error or navigation availability"}


def regression(records, saved_rows, old_summary, report_summary, module):
    by_time = {(r["method"], int(r["gps_ns"])): r for r in records}
    expected, differences = {}, []
    json_fields = {"model_checks", "nav_checks", "reference_checks", "reasons"}
    fields = list(module.FLAGS) + ["FINAL_STATE", "method", "window", "epoch_index", "gps_ns", "solver_original_accepted",
        "solver_converged", "solver_failure_category", "physical_satellite_count", "physical_rank_rechecked",
        "fault_monitor_redundancy", "MODEL_SCOPE", "FULL_PHYSICAL_MODEL_CONTRACT", "ITERATION_PATH_DOMAIN", *sorted(json_fields)]
    for r in saved_rows:
        key = (r["method"], int(r["gps_ns"]))
        if key in expected:
            raise InputError("DUPLICATE_REGRESSION_IDENTITY")
        expected[key] = r
        if key not in by_time:
            raise InputError("REGRESSION_TIME_OR_METHOD_MISMATCH")
        actual = by_time[key]
        if str(actual["epoch_index"]) != r["epoch_index"] or actual["window"] != r["window"]:
            raise InputError("REGRESSION_GRID_MISMATCH")
        for k in fields:
            a = actual[k]
            b = json.loads(r[k]) if k in json_fields else r[k]
            a = a if k in json_fields else "" if a is None else str(a)
            if a != b:
                differences.append({"key": [actual["dataset_id"], *key], "field": k, "new": a, "frozen": b})
    if expected.keys() != by_time.keys():
        raise InputError("REGRESSION_RECORD_COVERAGE_MISMATCH")
    for w, methods in report_summary["windows"].items():
        for m, s in methods.items():
            old = old_summary["windows"][w][m]
            for field in ("N_grid", "final_state_counts", "zero_redundancy_accepted_count"):
                if old[field] != s[field]:
                    differences.append({"window": w, "method": m, "field": field, "new": s[field], "frozen": old[field]})
            for flag in module.FLAGS:
                count = {v: sum(r[flag] == v for r in saved_rows if r["window"] == w and r["method"] == m) for v in (module.T, module.F, module.U)}
                if count != s["flags"][flag]:
                    differences.append({"window": w, "method": m, "flag_counts": flag, "new": s["flags"][flag], "frozen": count})
            if old["reference_qualified_P95"]["P95_horizontal_m"] is not None:
                differences.append({"field": "frozen_reference_P95_not_null", "window": w, "method": m})
    for field in ("reference_actual_eligibility_rate", "real_navigation_effective_ratio"):
        if old_summary[field] is not None:
            differences.append({"field": field, "frozen": old_summary[field], "new": None})
    return {"policy": COMPARISON_POLICY, "all_equal": not differences, "record_count": len(records),
            "fields_per_record": fields, "differences": differences, "float_tolerance": None,
            "new_fields": "source/evidence, per-flag reasons, SVD diagnostics and saved return information",
            "comparison_only_inputs": ["epoch_states.csv", "evaluation_summary.json"],
            "P95_recomputed": False, "null_semantics_preserved": not any("P95" in str(d) or "eligibility_rate" in str(d) or "effective_ratio" in str(d) for d in differences)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--protocol-id", required=True)
    parser.add_argument("--input-mode", required=True)
    args = parser.parse_args()
    module = load_module(args.module)
    if args.protocol_id != module.PROTOCOL_ID or args.input_mode != INPUT_MODE:
        raise InputError("UNSUPPORTED_ADAPTER_PROTOCOL_OR_INPUT_MODE")
    records, protocol, inputs, originals, _ = build_records(args.inputs, module)
    report_summary = summary(records, module)
    # Frozen qualifications are loaded only after all new checks have completed.
    comparison = regression(records, rows(args.inputs / "epoch_states.csv"), load(args.inputs / "evaluation_summary.json"), report_summary, module)
    returns_equal = all(r["solver_return_information"] == originals[(r["dataset_id"], r["method"], int(r["gps_ns"]))] for r in records)
    comparison["saved_return_information_unchanged"] = returns_equal
    if not returns_equal:
        comparison["differences"].append({"field": "saved_return_information", "reason": "SAVED_RETURN_CHANGED"})
        comparison["all_equal"] = False
    args.out.mkdir(parents=True, exist_ok=False)
    with (args.out / "epoch_qualification.csv").open("x", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in records)
    report_summary["input_identities"] = inputs
    report_summary["adapter"] = {"id": ADAPTER_ID, "version": VERSION, "module_version": module.VERSION}
    dump(args.out / "qualification_summary.json", report_summary)
    dump(args.out / "qualification_comparison.json", comparison)
    print(json.dumps({"records": len(records), "regression_equal": comparison["all_equal"], "new_solver_calls": 0}))
    return 0 if comparison["all_equal"] else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "INPUT_BLOCKED", "reason": type(exc).__name__ + ": " + str(exc)}), file=sys.stderr)
        raise SystemExit(2)
