"""Six real UrbanNav code solves, post-qualification, then frozen regression.

The positioning equations remain in the pinned, existing RTKLIB DLL. Python
marshalling and final diagnostic arithmetic follow P95-01 execute(), unchanged.
Historical solutions are opened only after fresh solver outputs have been sealed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import ctypes as ct
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

import numpy as np

ADAPTER_ID = "URBANNAV_REAL_REPLAY_V1"
INPUT_MODE = "PINNED_C1C_EXCERPT_V1"
VERSION = "1.3"
NATIVE_MODE = "NATIVE_RINEX_C1C_V1"
POLICY = "EXACT_REPLAY_SCIENCE_V1"
INDICES = [0, 548, 785]
METHODS = {"A": "SPP", "B": "SPP_FDE"}


class InputError(ValueError):
    pass


def load(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def rows(p):
    with p.open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(p, obj):
    with p.open("x", encoding="utf8") as h:
        h.write(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_csv(p, records):
    if not records:
        raise InputError("EMPTY_OUTPUT")
    with p.open("x", encoding="utf8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in records)


def module_at(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def checked_path(spec, key, base, digest):
    p = Path(spec[key])
    p = (p if p.is_absolute() else base / p).resolve()
    if not p.is_file():
        raise InputError(f"INPUT_MISSING: {key}: {p}")
    if sha(p) != digest:
        raise InputError(f"INPUT_VERSION_MISMATCH: {key}: {p}")
    return p


def prepare(directory, config, config_base, helpers, native_out=None):
    spec = config["replay"]
    if spec["indices"] != INDICES or spec["comparison_policy"] != POLICY or spec["input_mode"] not in (INPUT_MODE, NATIVE_MODE):
        raise InputError("REPLAY_SELECTION_OR_POLICY_MISMATCH")
    frozen, protocol = load(directory / "freeze.json"), load(directory / "protocol.json")
    names = ["freeze.json", "grid.csv", "spp_A.conf", "spp_B.conf"]
    if spec["input_mode"] == INPUT_MODE:
        names.append("raw_gps_fields.csv")
    for name in names:
        k = f"results/research_review/gnss_p95_01/{name}"
        if sha(directory / name) != protocol["preserved"][k]["sha256"]:
            raise InputError(f"EXCERPT_OR_CONFIG_VERSION_MISMATCH: {name}")
    grid = helpers.grid_index(rows(directory / "grid.csv"))
    selected = [grid[i] for i in INDICES]
    for g in selected:
        if (datetime(1980, 1, 6) + timedelta(seconds=int(g["gps_ns"]) // 1_000_000_000)).date().isoformat() != "2021-05-17":
            raise InputError("URBANNAV_DATE_MISMATCH")
    if spec["input_mode"] == NATIVE_MODE:
        native = module_at(Path(__file__).with_name("native_urbannav_obs.py"), "e4_native")
        if spec.get("exact_epochs") != native.TARGETS or spec.get("signal_policy") != "POSITIVE_FINITE_C1C_NO_SNR_V1":
            raise InputError("NATIVE_SELECTION_OR_SIGNAL_POLICY_MISMATCH")
        obs_path = checked_path(spec, "obs", config_base, frozen["input"]["sha256"])
        raw, provenance = native.parse_native(obs_path, selected)
        if native_out is None:
            raise InputError("NATIVE_OUTPUT_DIRECTORY_REQUIRED")
        dump(native_out / "native_obs_provenance.json", provenance)
        write_csv(native_out / "native_gps_fields.csv", [r for g in selected for r in raw[g["epoch_index"]]])
        dump(native_out / "native_measurement_seal.json", {
            "native_rows_sha256": sha(native_out / "native_gps_fields.csv"),
            "provenance_sha256": sha(native_out / "native_obs_provenance.json"),
            "historical_measurements_read": False, "navigation_calls": 0})
        historical = directory / "comparison/raw_gps_fields.csv"
        key = "results/research_review/gnss_p95_01/raw_gps_fields.csv"
        if sha(historical) != protocol["preserved"][key]["sha256"]:
            raise InputError("HISTORICAL_MEASUREMENT_VERSION_MISMATCH")
        comparison = native.compare_measurements(raw, historical, selected)
        dump(native_out / "measurement_comparison.json", comparison)
        if not comparison["all_equal"]:
            raise InputError("MEASUREMENT_RECONSTRUCTION_MISMATCH")
    else:
        all_raw = rows(directory / "raw_gps_fields.csv")
        raw = {}
        for g in selected:
            rr = [r for r in all_raw if r["epoch_index"] == g["epoch_index"]]
            for r in rr:
                helpers.bind_row(r, grid)
            eligible = [r for r in rr if r["eligible"] == "True"]
            if not eligible or len({r["satellite"] for r in eligible}) != len(eligible):
                raise InputError("MISSING_OR_DUPLICATE_CODES")
            if not all(Decimal(r["C1C_raw"]).is_finite() and Decimal(r["C1C_raw"]) > 0 and re.fullmatch(r"G[0-9]{2}", r["satellite"]) for r in eligible):
                raise InputError("CODE_QUALIFICATION_MISMATCH")
            raw[g["epoch_index"]] = rr
    nav = checked_path(spec, "nav", config_base, frozen["nav"]["sha256"])
    dll = checked_path(spec, "dll", config_base, frozen["dll"]["sha256"])
    a, b = ((directory / f"spp_{m}.conf").read_text().splitlines() for m in METHODS)
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    if len(a) != len(b) or len(diff) != 1 or "pos1-posopt5" not in diff[0][0]:
        raise InputError("CONFIG_PAIR_CHANGED")
    # This computational plan contains no old positions, satellite states,
    # reference paths or historical-result paths.
    plan = {"grid": selected, "raw": raw, "nav": nav, "dll": dll,
            "configs": {m: directory / f"spp_{m}.conf" for m in METHODS}, "expected_nav_records": 404}
    return plan, frozen, protocol


class Engine:
    """Typed calls to exactly the historical adapter binary; no positioning formulas."""
    def __init__(self, dll, nav):
        self.lib, self.nav = ct.CDLL(str(dll)), nav
        D = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        N = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
        for name, args, result in [
            ("setup", [ct.c_char_p, ct.c_char_p], ct.c_int),
            ("set_epoch", [ct.c_int, ct.c_double, ct.c_int, N, D], None),
            ("run_standard", [D, D, N, D, N, ct.c_char_p, ct.c_char_p], ct.c_int),
            ("export_code_terms", [D, ct.c_char_p], ct.c_int),
            ("start_trace", [ct.c_char_p], None), ("end_trace", [], None),
            ("chi_threshold", [ct.c_int], ct.c_double)]:
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result

    def setup(self, config):
        return self.lib.setup(str(config.resolve()).encode(), str(self.nav).encode())

    def fit(self, g, obs, trace, export):
        n = len(obs)
        self.lib.start_trace(str(trace.resolve()).encode())
        try:
            t0 = time.perf_counter_ns()
            self.lib.set_epoch(int(g["week"]), float(g["tow_decimal"]), n,
                np.array([int(r["satellite"][1:]) for r in obs], dtype=np.int32),
                np.array([float(r["C1C_raw"].replace("D", "E").replace("d", "e")) for r in obs], dtype=np.float64))
            t1 = time.perf_counter_ns()
            x, az, used, post, flags = np.zeros(4), np.zeros(2*n), np.zeros(n, np.int32), np.zeros(n), np.zeros(4, np.int32)
            m0, m1 = ct.create_string_buffer(512), ct.create_string_buffer(512)
            state = progress(export.parent, "NAVIGATION_CALL")
            progress(export.parent, "NAVIGATION_CALL", top_level_started=state["top_level_started"]+1)
            accepted = bool(self.lib.run_standard(x, az, used, post, flags, m0, m1))
            t2 = time.perf_counter_ns()
            dump(export.with_name(export.stem + "_immediate_return.json"), {
                "accepted": accepted, "flags": flags.tolist(), "x": x.tolist(),
                "used": used.tolist(), "post": post.tolist(),
                "raw_initial_message": m0.value.decode(errors="replace"),
                "raw_final_message": m1.value.decode(errors="replace")})
            state = progress(export.parent, "FINAL_MODEL_EXPORT")
            progress(export.parent, "FINAL_MODEL_EXPORT", top_level_returned=state["top_level_returned"]+1)
            if flags[3]:
                if export.exists():
                    raise InputError("MODEL_EXPORT_ALREADY_EXISTS")
                if self.lib.export_code_terms(np.r_[x, np.zeros(3)], str(export.resolve()).encode()) != n:
                    raise InputError("MODEL_EXPORT_COUNT_MISMATCH")
                model_rows = rows(export)
            else:
                model_rows = []
        finally:
            self.lib.end_trace()
        return {"accepted": accepted, "flags": flags.tolist(), "x": x.tolist(), "used": used.tolist(),
                "post": post.tolist(), "raw_initial_message": m0.value.decode(errors="replace"),
                "raw_final_message": m1.value.decode(errors="replace"), "model_rows": model_rows,
                "core_ms": (t2-t0)/1e6, "sat_state_ms": (t1-t0)/1e6, "fit_FDE_ms": (t2-t1)/1e6,
                "chi_threshold": float(self.lib.chi_threshold(int(sum(used))-4)) if sum(used)>4 else None}


def final_diagnostics(rec, good, recorder=None):
    """Same final NumPy diagnostics as P95-01 execute(); no new model."""
    angles = H = rank = G = Q = d = sums = None
    if good:
        residual = np.array([float(t["residual_m"]) for t in good])
        variance = np.array([float(t["variance_m2"]) for t in good])
        rec.update(residual_rms_m=float(np.sqrt(np.mean(residual**2))), weighted_sum_squares=float(np.sum(residual**2/variance)), physical_dof=len(good)-4)
        angles = np.array([[float(t["az_rad"]), float(t["el_rad"])] for t in good])
        if recorder is not None and not np.all(np.isfinite(angles)):
            raise ValueError("NONFINITE_DOP_INPUT")
        a, e = angles.T
        H = np.c_[np.cos(e)*np.sin(a), np.cos(e)*np.cos(a), np.sin(e), np.ones(len(e))]
        rank = int(np.linalg.matrix_rank(H))
        rec["physical_rank"] = rank
        if rank == 4:
            G = H.T@H
            Q = np.linalg.inv(G)
            d = np.diag(Q)
            s0 = sum(d); gdop = float(np.sqrt(s0))
            s1 = sum(d[:3]); pdop = float(np.sqrt(s1))
            s2 = sum(d[:2]); hdop = float(np.sqrt(s2))
            s3 = d[2]; vdop = float(np.sqrt(s3))
            sums = np.array([s0, s1, s2, s3])
            rec.update(gdop=gdop, pdop=pdop, hdop=hdop, vdop=vdop)
    x = rec["state_ecef_m"]
    a, e2 = 6378137., 6.6943799901413165e-3
    xy, z = float(np.hypot(x[0], x[1])), float(x[2])
    lat = np.arctan2(z, xy*(1-e2))
    for _ in range(12):
        nn = a/np.sqrt(1-e2*np.sin(lat)**2)
        lat = np.arctan2(z+e2*nn*np.sin(lat), xy)
    height = float(xy/np.cos(lat)-a/np.sqrt(1-e2*np.sin(lat)**2))
    rec["model_height_m"] = height
    rec["SAAS_out"] = height < -100 or height > 10000 or any(float(t["el_rad"]) <= 0 for t in good)
    if recorder is not None:
        recorder.capture(rec, good, angles, H, rank, G, Q, d, sums)


def progress(out, stage, **updates):
    path = out / "execution_progress.json"
    state = load(path) if path.exists() else {"top_level_started": 0, "top_level_returned": 0}
    state.update(failure_stage=stage, **updates)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf8")
    temporary.replace(path)
    return state


def execute_measurements(plan, out, engine_factory=Engine):
    record_module = module_at(Path(__file__).with_name("dop_recorder.py"), "e16_dop_recorder")
    recorder = record_module.Recorder(out / "dop_evidence", Path(__file__)) if plan.get("dop_recording", True) else None
    engine = engine_factory(plan["dll"], plan["nav"])
    results, terms, calls = [], [], []
    for method in METHODS:
        nav_count = engine.setup(plan["configs"][method])
        if nav_count != plan["expected_nav_records"]:
            raise InputError(f"NAV_DECODE_COUNT_MISMATCH: {nav_count}")
        for g in plan["grid"]:
            tick_epoch = time.perf_counter_ns()
            obs = [r for r in plan["raw"].get(g["epoch_index"], []) if r["eligible"] == "True"]
            if plan.get("window_mode") and (g["gps_ns"] in plan["missing_times"] or not obs):
                reason = "MISSING_OBS_EPOCH" if g["gps_ns"] in plan["missing_times"] else "NO_ELIGIBLE_C1C"
                results.append(dict(method=method, **g, input_count=0,
                    candidate_count=len(plan["raw"].get(g["epoch_index"], [])), input_satellites=[],
                    obs_present=reason != "MISSING_OBS_EPOCH", solver_called=False,
                    accepted=False, converged=False, initial_accepted=False, initial_converged=False,
                    FDE_attempted=False, used_satellites=[], FDE_excluded=[], state_ecef_m=None,
                    clock_m=None, clock_s=None, initial_message=reason, final_message=reason,
                    raw_initial_message=reason, raw_final_message=reason, failure_category=reason,
                    execution_stage="NOT_CALLED", core_ms=None, sat_state_ms=None, fit_FDE_ms=None,
                    epoch_elapsed_ms=(time.perf_counter_ns()-tick_epoch)/1e6,
                    residual_rms_m=None, weighted_sum_squares=None, physical_dof=None, physical_rank=None,
                    chi_threshold=None, gdop=None, pdop=None, hdop=None, vdop=None, model_height_m=None, SAAS_out=False))
                if recorder is not None: recorder.unavailable(results[-1], reason)
                continue
            trace = out / f"trace_{method}_{g['epoch_index']}.txt"
            previous = progress(out, "SOLVER_CALL", current_method=method, current_epoch=g["epoch_index"])
            if previous["top_level_started"] >= plan.get("max_top_level_calls", 6):
                raise RuntimeError("PER_RUN_NAVIGATION_BUDGET_EXCEEDED")
            if not isinstance(engine, Engine):  # substitute-engine tests only
                progress(out, "SOLVER_CALL", top_level_started=previous["top_level_started"]+1)
            fit = engine.fit(g, obs, trace, out / f"export_{method}_{g['epoch_index']}.csv")
            progress(out, "SOLVER_EXPORT_AND_TRACE", top_level_returned=previous["top_level_returned"]+1)
            # Preserve the raw returned state and flags before any parsing or
            # diagnostic step can fail. Never recover it from a historical fit.
            dump(out / f"raw_return_{method}_{g['epoch_index']}.json", fit)
            flags = fit["flags"]
            rec = dict(method=method, **g, input_count=len(obs), input_satellites=[r["satellite"] for r in obs],
                initial_accepted=bool(flags[0]), initial_converged=bool(flags[1]), FDE_attempted=bool(flags[2]),
                converged=bool(flags[3]), accepted=fit["accepted"],
                initial_message="" if flags[0] else fit["raw_initial_message"],
                final_message="" if fit["accepted"] else fit["raw_final_message"],
                raw_initial_message=fit["raw_initial_message"], raw_final_message=fit["raw_final_message"],
                used_satellites=[r["satellite"] for r,u in zip(obs,fit["used"]) if u], FDE_excluded=[],
                state_ecef_m=fit["x"][:3] if flags[3] else None, clock_m=float(fit["x"][3]) if flags[3] else None,
                clock_s=float(fit["x"][3]/299792458) if flags[3] else None,
                core_ms=fit["core_ms"], sat_state_ms=fit["sat_state_ms"], fit_FDE_ms=fit["fit_FDE_ms"],
                residual_rms_m=None, weighted_sum_squares=None, physical_dof=None, chi_threshold=fit["chi_threshold"],
                gdop=None, pdop=None, hdop=None, vdop=None, physical_rank=None, model_height_m=None, SAAS_out=False)
            text = trace.read_text(errors="replace")
            estpos_calls = len(re.findall(r"^(?:[0-9] )?estpos  :", text, re.M))
            fde_calls = len(re.findall(r"^(?:[0-9] )?raim_fde: .* n=", text, re.M))
            satposs_calls = len(re.findall(r"^(?:[0-9] )?satposs :", text, re.M))
            rec["FDE_excluded"] = re.findall(r"(G\d+) excluded by raim", text)
            if (estpos_calls < 1 and not (plan.get("window_mode") and not flags[3] and not fit["accepted"])) or fde_calls != int(bool(flags[2])):
                raise RuntimeError("TRACE_CALL_ACCOUNTING_MISMATCH")
            calls.append({"method": method, "epoch_index": g["epoch_index"], "top_level": 1, "set_epoch_satposs": 1,
                          "satposs_trace_entries": satposs_calls,
                          "estpos_trace_entries": estpos_calls, "FDE_invocations": fde_calls,
                          "FDE_internal_candidate_fits": max(0, estpos_calls-1), "nav_records": nav_count,
                          "satellite_position_evaluations": "NOT_INSTRUMENTED", "export_ephemeris_recomputations": "NOT_INSTRUMENTED"})
            good = []
            if flags[3]:
                if len(fit["model_rows"]) != len(obs):
                    raise InputError("FINAL_MODEL_ROW_COUNT_MISMATCH")
                for j,(t,r,u) in enumerate(zip(fit["model_rows"], obs, fit["used"])):
                    if t["sv"] != r["satellite"] or float(t["raw_code_m"]) != float(r["C1C_raw"].replace("D", "E").replace("d", "e")):
                        raise InputError("EXPORTED_MEASUREMENT_IDENTITY_MISMATCH")
                    if u and abs(float(t["residual_m"])-fit["post"][j]) >= 1e-3:
                        raise InputError("POSTFIT_EXPORT_MISMATCH")
                    terms.append(dict(method=method, window=g["window"], epoch_index=g["epoch_index"], accepted=rec["accepted"], used=bool(u),
                        S1C_raw=r["S1C_raw"], S1C_unit="UNKNOWN", C1C_SSI=r["C1C_SSI"], **t))
                    if u:
                        good.append(t)
                final_diagnostics(rec, good, recorder)
            else:
                if recorder is not None: recorder.unavailable(rec, "SOLVER_NOT_CONVERGED")
            msg = rec["final_message"]
            rec["failure_category"] = "ACCEPTED" if rec["accepted"] else "ACTIVE_QUALITY_REJECT" if rec["converged"] and ("chi-square" in msg or "gdop" in msg) else "NO_ACCEPTED_SOLUTION"
            if plan.get("window_mode"):
                rec.update(solver_called=True, obs_present=True, candidate_count=len(plan["raw"][g["epoch_index"]]),
                           execution_stage="RESULT_SAVED", epoch_elapsed_ms=(time.perf_counter_ns()-tick_epoch)/1e6)
            results.append(rec)
    if recorder is not None: recorder.finish()
    return results, terms, calls


def qualify_fresh(results, terms, plan, module, protocol, source_sha, out):
    dataset = "UrbanNav-HK-Medium-Urban-1/ublox.f9p.splitter/GPS-C1C/" + source_sha
    quals = []
    for n,r in enumerate(results):
        model = [t for t in terms if t["method"] == r["method"] and t["epoch_index"] == r["epoch_index"]]
        q = module.qualify_saved_epoch(r, plan["raw"][r["epoch_index"]], model, protocol, time_valid=module.T)
        quals.append({"dataset_id": dataset, "method_id": METHODS[r["method"]], "method": r["method"],
                      "epoch_index": r["epoch_index"], "window": r["window"], "gps_ns": r["gps_ns"], "week": r["week"], "tow_decimal": r["tow_decimal"],
                      "source_result_id": sha(out / "fresh_results.json") + f"#/{n}",
                      "protocol_id": protocol["protocol_id"], "model_validation_scope": module.MODEL_SCOPE,
                      "source_evidence": {"fresh_result_pointer": f"fresh_results.json#/{n}", "fresh_terms_sha256": sha(out / "fresh_satellite_terms.csv"),
                          "raw_code_source": plan.get("input_mode", INPUT_MODE) + "; newly decoded OBS" if plan.get("input_mode") == NATIVE_MODE else "pinned raw_gps_fields.csv, not receiver state", "policy_source": "unchanged protocol.json",
                          "module_version": module.VERSION}, **q})
    return quals


def compare_fresh(results, terms, quals, directory):
    # This is the first opening of any old navigation/model/qualification table.
    old = {(m,str(r["epoch_index"])):r for m in METHODS for r in load(directory / f"comparison/baseline_{m}.json")}
    old_terms = {(r["method"],r["epoch_index"],r["sv"]):r for r in rows(directory / "comparison/satellite_terms.csv")}
    old_quals = {(r["method"],r["epoch_index"]):r for r in rows(directory / "comparison/epoch_states.csv")}
    ignored = {"core_ms", "fit_FDE_ms", "sat_state_ms"}
    differences, maxima, checked = [], {}, Counter()
    def same(k, actual, expected, key):
        checked[k] += 1
        if isinstance(actual, (float,int)) and not isinstance(actual, bool) and isinstance(expected, (float,int)):
            delta = abs(actual-expected)
            maxima[k] = max(maxima.get(k, 0.), delta)
        elif isinstance(actual, list) and isinstance(expected, list) and all(type(v) in (float,int) for v in actual+expected):
            maxima[k] = max(maxima.get(k, 0.), max([abs(x-y) for x,y in zip(actual,expected)] or [0.]))
        if actual != expected:
            differences.append({"identity": key, "field": k, "new": actual, "frozen": expected})
    for r in results:
        key = (r["method"],r["epoch_index"])
        expected = old[key]
        for k,v in expected.items():
            if k not in ignored:
                same(k, r[k], v, key)
    for t in terms:
        key = (t["method"],t["epoch_index"],t["sv"])
        expected = old_terms[key]
        for k,v in expected.items():
            value = t[k]
            if k in {"method","window","epoch_index","sv","S1C_unit","C1C_SSI","accepted","used"}:
                same("term."+k, str(value), v, key)
            else:
                same("term."+k, float(value), float(v), key)
    for q in quals:
        key = (q["method"],q["epoch_index"])
        for k in ["OBS_VALID","NAV_VALID","MODEL_VALID","SOLVER_VALID","REFERENCE_VALID","FINAL_STATE"]:
            same(k, q[k], old_quals[key][k], key)
        for k in ["model_checks","nav_checks","reference_checks","reasons"]:
            same(k, q[k], json.loads(old_quals[key][k]), key)
    return {"policy": POLICY, "all_equal": not differences, "differences": differences, "numeric_max_abs_difference": maxima,
            "checked_fields": dict(checked), "ignored_execution_fields": sorted(ignored), "float_tolerance": 0,
            "extra_fields_not_in_history": ["raw_initial_message","raw_final_message","source_evidence","run metadata"],
            "records": len(results), "model_rows": len(terms)}


def compare_engineering(results, terms, quals, directory, out):
    """Additional E3 comparison after new outputs/qualification are saved."""
    old = load(directory / "comparison/e3_fresh_results.json")
    old_terms = rows(directory / "comparison/e3_satellite_terms.csv")
    old_q = rows(directory / "comparison/e3_epoch_qualification.csv")
    ignored = {"core_ms", "fit_FDE_ms", "sat_state_ms"}
    differences = []
    if len(old) != len(results):
        differences.append("result count")
    for a, b in zip(results, old):
        for k in b:
            if k not in ignored and a.get(k) != b[k]:
                differences.append({"identity": [b["method"], b["epoch_index"]], "field": k, "new": a.get(k), "E3": b[k]})
    # Compare the serialized cells exactly, including all model coefficients.
    new_terms = rows(out / "fresh_satellite_terms.csv")
    if new_terms != old_terms:
        differences.append({"field": "all model CSV cells", "equal": False})
    flags = ["OBS_VALID", "NAV_VALID", "MODEL_VALID", "SOLVER_VALID", "REFERENCE_VALID", "FINAL_STATE"]
    for a, b in zip(quals, old_q):
        for k in ["epoch_index", "method", "gps_ns", "week", "tow_decimal", *flags]:
            if str(a[k]) != b[k]:
                differences.append({"identity": [b["method"], b["epoch_index"]], "field": k})
        for k in ("model_checks", "nav_checks", "reference_checks", "reasons"):
            if a[k] != json.loads(b[k]):
                differences.append({"identity": [b["method"], b["epoch_index"]], "field": k})
    if len(quals) != len(old_q):
        differences.append("qualification count")
    return {"policy": POLICY, "all_equal": not differences, "differences": differences,
            "ignored_execution_fields": sorted(ignored), "source_identity_fields_compared_separately": True,
            "float_tolerance": 0}


def run(directory, out, config_path, module_path):
    config = load(config_path)
    if "runtime" in config:
        window = module_at(Path(__file__).with_name("window_urbannav.py"), "e5_window")
        return window.run(config, config_path, out, module_path, sys.modules.get(__name__) or module_at(Path(__file__), "e5_engine"))
    helper_path = Path(config["replay"]["saved_adapter"])
    helpers = module_at(helper_path, "e3_saved_helpers")
    module = module_at(module_path, "e3_qualification_core")
    native_mode = config["replay"]["input_mode"] == NATIVE_MODE
    if native_mode:
        out.mkdir(parents=True, exist_ok=False)
        progress(out, "NATIVE_OBSERVATION_PRECHECK")
    plan, frozen, protocol = prepare(directory, config, config_path.parent, helpers, out) if native_mode else prepare(directory, config, config_path.parent, helpers)
    module.validate_protocol(protocol)
    if not native_mode:
        out.mkdir(parents=True, exist_ok=False)
    if native_mode:
        plan["input_mode"] = NATIVE_MODE
    (out / "execution_config.json").write_bytes(config_path.read_bytes())
    dump(out / "replay_freeze.json", {"indices": INDICES,"methods": METHODS,"grid": plan["grid"],"comparison_policy": POLICY,
        "numeric_tolerance":0,"input_mode":config["replay"]["input_mode"],"full_RINEX_reparsed":native_mode,"initialization":"origin/zero clock; unchanged internal FDE loop",
        "nav_sha256":sha(plan["nav"]),"dll_sha256":sha(plan["dll"]),"reference_runtime_access":False})
    results, terms, calls = execute_measurements(plan, out)
    dump(out / "fresh_results.json", results)
    write_csv(out / "fresh_satellite_terms.csv", terms)
    dump(out / "solver_outputs_seal.json", {"fresh_results_sha256":sha(out/"fresh_results.json"),"fresh_terms_sha256":sha(out/"fresh_satellite_terms.csv"),
        "top_level_calls":len(results),"calls":calls,"historical_results_read_before_this_seal":False})
    progress(out, "QUALIFICATION")
    quals = qualify_fresh(results,terms,plan,module,protocol,frozen["input"]["sha256"],out)
    write_csv(out / "epoch_qualification.csv", quals)
    progress(out, "FROZEN_RESULT_COMPARISON")
    comparison = compare_fresh(results,terms,quals,directory)
    if native_mode:
        engineering = compare_engineering(results, terms, quals, directory, out)
        dump(out / "engineering_comparison.json", engineering)
        comparison["engineering_baseline_equal"] = engineering["all_equal"]
        comparison["all_equal"] = comparison["all_equal"] and engineering["all_equal"]
    dump(out / "replay_comparison.json", comparison)
    summary = {"adapter_id":ADAPTER_ID,"adapter_version":VERSION,"module_version":module.VERSION,"top_level_calls":len(results),
        "FDE_internal_candidate_fits":sum(c["FDE_internal_candidate_fits"] for c in calls),
        "set_epoch_satposs_calls":sum(c["set_epoch_satposs"] for c in calls),"satellite_position_evaluations":"NOT_INSTRUMENTED",
        "counts":dict(Counter(q["FINAL_STATE"] for q in quals)),"comparison_equal":comparison["all_equal"],
        "P95_recomputed":False,"reference_qualified_P95":None,"real_navigation_effective_ratio":None,"peak_memory":"NOT_MEASURED"}
    dump(out / "replay_summary.json",summary)
    progress(out, "COMPLETED")
    print(json.dumps(summary))
    return 0 if comparison["all_equal"] else 3


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs","out","config","module"):
        p.add_argument("--"+name,type=Path,required=True)
    a = p.parse_args()
    try:
        return run(a.inputs,a.out,a.config,a.module)
    except Exception as exc:
        ledger = load(a.out / "execution_progress.json") if (a.out / "execution_progress.json").is_file() else {"top_level_started": 0, "failure_stage": "INPUT_PRECHECK"}
        started = ledger["top_level_started"] > 0
        receipt = {**ledger, "status": "FAILED" if started else "INPUT_BLOCKED", "reason": type(exc).__name__ + ": " + str(exc)}
        if a.out.is_dir() and not (a.out / "failure_receipt.json").exists():
            dump(a.out / "failure_receipt.json", receipt)
        print(json.dumps(receipt), file=sys.stderr)
        return 1 if started else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InputError as exc:
        print(json.dumps({"status":"INPUT_BLOCKED","reason":str(exc)}),file=sys.stderr)
        raise SystemExit(2)
