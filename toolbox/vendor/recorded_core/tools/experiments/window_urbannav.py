"""Configured native window, using the existing engine and pure qualification.

No historical file is required for prepare() or execute(). Comparison reads are
deferred until the runtime seal exists. This is not a second navigation engine.
"""
from collections import Counter
from decimal import Decimal
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

MODE = "NATIVE_OBS_WINDOW_V1"
VERSION = "1.1"


def slots(spec):
    week, step = spec["gps_week"], spec["step_ns"]
    if type(week) is not int or week < 0 or type(step) is not int or step <= 0:
        raise ValueError("INVALID_WINDOW_WEEK_OR_STEP")
    endpoints = []
    for key in ("start_tow", "end_tow"):
        if not isinstance(spec[key], str):
            raise ValueError("TOW_MUST_BE_DECIMAL_STRING")
        value = Decimal(spec[key]) * 10**9
        if not value.is_finite() or value != value.to_integral_value() or not 0 <= value < 604800*10**9:
            raise ValueError("INVALID_EXACT_TOW")
        endpoints.append(int(value))
    start, end = endpoints
    if end < start or (end-start) % step:
        raise ValueError("WINDOW_ENDPOINT_OR_STEP_MISMATCH")
    n = (end-start)//step+1
    if n > 100000:
        raise ValueError("REQUESTED_WINDOW_RESOURCE_LIMIT_100000_SLOTS")
    return [{"window": "configured_runtime", "epoch_index": str(i), "slot_index": i,
             "gps_ns": str(week*604800*10**9 + tow), "week": str(week),
             "tow_decimal": format(Decimal(tow)/10**9, "f")}
            for i, tow in enumerate(range(start, end+1, step))]


def checked(item, base, engine):
    path = Path(item["path"])
    path = (path if path.is_absolute() else base/path).resolve()
    if not path.is_file():
        raise ValueError(f"RUNTIME_INPUT_MISSING: {path}")
    if engine.sha(path) != item["sha256"]:
        raise ValueError(f"RUNTIME_IDENTITY_MISMATCH: {path}")
    return path


def validate_rules(rules, module):
    module.validate_protocol(rules)
    if rules.get("rules_id") != "URBANNAV_FINAL_RESIDUAL_RUNTIME_V1" or "preserved" in rules:
        raise ValueError("RUNTIME_RULES_MUST_NOT_BIND_HISTORICAL_RESULTS")
    if rules.get("source_numeric_rules") != module.SOURCE_RULES or rules.get("qualification_implementation") != module.VERSION:
        raise ValueError("RUNTIME_RULE_IMPLEMENTATION_MISMATCH")


def prepare(config, base, engine, module):
    spec = config["runtime"]
    if spec.get("mode") != MODE or spec.get("signal_policy") != "POSITIVE_FINITE_C1C_NO_SNR_V1":
        raise ValueError("UNSUPPORTED_WINDOW_INPUT_POLICY")
    grid = slots(spec["window"])
    inputs = {k: checked(spec[k], base, engine) for k in ("obs", "nav", "dll", "rules")}
    configs = {m: checked(spec["scientific_configs"][m], base, engine) for m in engine.METHODS}
    a, b = (configs[m].read_text().splitlines() for m in engine.METHODS)
    difference = [(x, y) for x, y in zip(a, b) if x != y]
    if len(a) != len(b) or len(difference) != 1 or "pos1-posopt5" not in difference[0][0]:
        raise ValueError("SCIENTIFIC_METHOD_PAIR_CHANGED")
    rules = engine.load(inputs["rules"])
    validate_rules(rules, module)
    # A supplied reference contract is evidence, never an estimation input.
    reference = {k: module.U for k in module.REFERENCE_FIELDS}
    if spec.get("reference_contract") is not None:
        reference_path = checked(spec["reference_contract"], base, engine)
        supplied = engine.load(reference_path)
        reference = {k: module.truth(supplied.get(k)) for k in module.REFERENCE_FIELDS}
    rules = {**rules, "reference": reference}
    native = engine.module_at(Path(__file__).with_name("native_urbannav_obs.py"), "e5_native")
    targets = [{k: g[k] for k in ("epoch_index", "week", "tow_decimal", "gps_ns")} for g in grid]
    raw, provenance = native.parse_native(inputs["obs"], grid, targets, allow_missing=True)
    provenance["native_adapter_file"] = str(Path(native.__file__).resolve())
    found = {e["gps_ns"]: e for e in provenance["epochs"]}
    missing = []
    for g in grid:
        epoch = found.get(g["gps_ns"])
        g["source_epoch_index"] = epoch["source_epoch_index"] if epoch else None
        if epoch is None:
            missing.append(g["gps_ns"])
        raw.setdefault(g["epoch_index"], [])
    plan = {"grid": grid, "raw": raw, "nav": inputs["nav"], "dll": inputs["dll"], "configs": configs,
            "expected_nav_records": spec["expected_nav_records"], "input_mode": MODE,
            "window_mode": True, "missing_times": missing, "max_top_level_calls": len(grid)*len(engine.METHODS)}
    return plan, rules, provenance, inputs


def table(engine, path, values, empty_columns):
    if values:
        engine.write_csv(path, values)
    else:
        with path.open("x", encoding="utf8") as h:
            h.write(",".join(empty_columns)+"\n")


def qualify(results, terms, plan, rules, provenance, inputs, out, engine, module):
    dataset = "UrbanNav-HK-Medium-Urban-1/ublox.f9p.splitter/GPS-C1C/"+provenance["obs_sha256"]
    rows = []
    result_sha, rules_sha, nav_sha = engine.sha(out/"fresh_results.json"), engine.sha(inputs["rules"]), engine.sha(inputs["nav"])
    for i, r in enumerate(results):
        model = [t for t in terms if t["method"] == r["method"] and t["epoch_index"] == r["epoch_index"]]
        q = module.qualify_saved_epoch(r, plan["raw"][r["epoch_index"]], model, rules,
                                      time_valid=module.T if r["obs_present"] else module.F)
        rows.append({"dataset_id": dataset, "method_id": engine.METHODS[r["method"]], "method": r["method"],
                     **{k: r[k] for k in ("epoch_index", "slot_index", "source_epoch_index", "window", "gps_ns", "week", "tow_decimal")},
                     "source_result_id": result_sha+f"#/{i}",
                     "rules_id": rules["rules_id"], "rules_sha256": rules_sha,
                     "inherited_protocol_id": rules["inherited_protocol_id"],
                     "model_validation_scope": module.MODEL_SCOPE,
                     "source_evidence": {"fresh_result_pointer": f"fresh_results.json#/{i}",
                         "obs_sha256": provenance["obs_sha256"], "nav_sha256": nav_sha,
                         "fresh_terms_pointer": f"fresh_satellite_terms.csv:method={r['method']},epoch_index={r['epoch_index']}",
                         "reference_contract": "ABSENT; all fields UNKNOWN" if all(v == module.U for v in rules["reference"].values()) else "explicit runtime contract",
                         "qualification_implementation": module.VERSION}, **q})
    return rows


def optional_comparison(config, out, base, engine):
    """No path lookup, hashing or historical reads when comparison is disabled."""
    spec = config.get("comparison", {})
    if not isinstance(spec, dict) or type(spec.get("enabled", False)) is not bool:
        raise ValueError("INVALID_COMPARISON_SWITCH")
    if not spec.get("enabled", False):
        return {"status": "NOT_RUN", "reason": "COMPARISON_DISABLED", "all_equal": None, "historical_inputs_read": []}
    # Guard even direct calls; never read historical bytes before the new seal.
    seal_path = out/"runtime_outputs_seal.json"
    if not seal_path.is_file():
        raise ValueError("RUNTIME_OUTPUT_SEAL_REQUIRED_BEFORE_COMPARISON")
    seal = engine.load(seal_path)
    for name, digest in seal["files"].items():
        if engine.sha(out/name) != digest:
            raise ValueError("RUNTIME_OUTPUT_CHANGED_BEFORE_COMPARISON")
    if spec.get("policy") != engine.POLICY:
        raise ValueError("UNSUPPORTED_COMPARISON_POLICY")
    identities = []
    try:
        paths = {}
        for key in ("results", "terms", "qualification", *(["observations"] if "observations" in spec["files"] else [])):
            path = checked(spec["files"][key], base, engine)
            paths[key] = path
            identities.append({"role": key, "path": str(path), "sha256": spec["files"][key]["sha256"]})
    except (OSError, ValueError) as exc:
        return {"status": "NOT_RUN", "reason": str(exc), "all_equal": None, "historical_inputs_read": identities}
    old = engine.load(paths["results"])
    old_terms, old_q = engine.rows(paths["terms"]), engine.rows(paths["qualification"])
    fresh = engine.load(out/"fresh_results.json")
    terms, quals = engine.rows(out/"fresh_satellite_terms.csv"), engine.rows(out/"epoch_qualification.csv")
    differences, maxima, checked_fields = [], {}, Counter()
    def same(field, a, b, identity):
        checked_fields[field] += 1
        if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)):
            maxima[field] = max(maxima.get(field, 0.), abs(a-b))
        if isinstance(a, list) and isinstance(b, list) and all(type(x) in (float, int) for x in a+b) and len(a) == len(b):
            maxima[field] = max(maxima.get(field, 0.), max([abs(x-y) for x, y in zip(a, b)] or [0.]))
        if a != b:
            differences.append({"identity": identity, "field": field, "new": a, "historical": b})
    excluded = {"core_ms", "fit_FDE_ms", "sat_state_ms", "epoch_elapsed_ms", "epoch_index", "window", "source_result_id"}
    for ns in spec["gps_ns"]:
        for method in engine.METHODS:
            a = [r for r in fresh if r["gps_ns"] == ns and r["method"] == method]
            b = [r for r in old if r["gps_ns"] == ns and r["method"] == method]
            if len(a) != 1 or len(b) != 1:
                raise ValueError("COMPARISON_TIME_IDENTITY_MISSING_OR_DUPLICATE")
            a, b = a[0], b[0]; identity = [ns, method]
            for key in b:
                if key not in excluded:
                    same(key, a.get(key), b[key], identity)
            aa = [r for r in terms if r["method"] == method and r["epoch_index"] == a["epoch_index"]]
            bb = [r for r in old_terms if r["method"] == method and r["epoch_index"] == b["epoch_index"]]
            same("model_count", len(aa), len(bb), identity)
            for x, y in zip(aa, bb):
                for key in y:
                    if key not in ("epoch_index", "window"):
                        same("term."+key, x.get(key), y[key], identity)
            aq = [r for r in quals if r["gps_ns"] == ns and r["method"] == method]
            bq = [r for r in old_q if r["gps_ns"] == ns and r["method"] == method]
            if len(aq) != 1 or len(bq) != 1:
                raise ValueError("COMPARISON_QUALIFICATION_IDENTITY_ERROR")
            for key in (*("OBS_VALID", "NAV_VALID", "MODEL_VALID", "SOLVER_VALID", "REFERENCE_VALID"), "FINAL_STATE", "obs_checks", "nav_checks", "model_checks", "solver_checks"):
                same(key, aq[0][key], bq[0][key], identity)
            if spec.get("qualification_evidence_policy") == "SAME_REFERENCE_CONTRACT_V1":
                for key in ("reference_checks", "reason_codes", "reasons"):
                    same(key, aq[0][key], bq[0][key], identity)
    if "observations" in paths:
        same("ordered_native_observation_cells", engine.rows(out/"native_gps_fields.csv"),
             engine.rows(paths["observations"]), "all requested epochs")
    for name, digest in seal["files"].items():
        if engine.sha(out/name) != digest:
            raise ValueError("COMPARISON_MODIFIED_RUNTIME_OUTPUT")
    return {"status": "MATCHED" if not differences else "MISMATCH", "all_equal": not differences,
            "policy": engine.POLICY, "float_tolerance": 0, "differences": differences,
            "numeric_max_abs_difference": maxima, "checked_fields": dict(checked_fields),
            "historical_inputs_read": identities, "runtime_outputs_unchanged": True,
            "separate_evidence_fields": ["source IDs", "window/slot indices", "reference subchecks/reasons: no reference contract in this run"],
            "reference_difference": ("reference checks and reasons compared exactly" if spec.get("qualification_evidence_policy") == "SAME_REFERENCE_CONTRACT_V1" else
                                     "E4 nominal_bracketing TRUE; absent runtime reference contract gives UNKNOWN; overall REFERENCE UNKNOWN in both")}


def run(config, config_path, out, module_path, engine):
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=False)
    engine.progress(out, "WINDOW_INPUT_PRECHECK")
    accesses = []
    def record(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            accesses.append({"path": str(args[0]), "mode": str(args[1]), "flags": args[2]})
        elif event == "ctypes.dlopen":
            accesses.append({"path": str(args[0]), "mode": "DLL_LOAD", "flags": None})
    sys.addaudithook(record)
    try:
        module = engine.module_at(module_path, "e5_pure_qualification")
        plan, rules, provenance, inputs = prepare(config, config_path.parent, engine, module)
        package_root = Path(__file__).resolve().parents[2]
        loaded = {"window_adapter": str(Path(__file__).resolve()), "replay_engine": str(Path(engine.__file__).resolve()),
                  "qualification_module": str(Path(module.__file__).resolve()), "native_adapter": provenance["native_adapter_file"]}
        loaded.update({name: str(Path(value.__file__).resolve()) for name, value in list(sys.modules.items())
                       if name.startswith("gnss_toolbox") and getattr(value, "__file__", None)})
        if any(not Path(path).is_relative_to(package_root) for path in loaded.values()):
            raise ValueError("FIRST_PARTY_IMPORT_ESCAPED_CODE_ROOT")
        engine.dump(out/"first_party_modules.json", {"code_root": str(package_root), "modules": loaded,
                    "all_within_code_root": True, "python_executable": sys.executable, "sys_path": sys.path})
        engine.dump(out/"execution_config.json", config)
        engine.dump(out/"effective_rules.json", rules)
        engine.dump(out/"native_obs_provenance.json", provenance)
        table(engine, out/"native_gps_fields.csv", [r for g in plan["grid"] for r in plan["raw"][g["epoch_index"]]], ["epoch_index", "satellite", "C1C_raw", "eligible"])
        engine.dump(out/"requested_slots.json", [{**g, "obs_present": g["gps_ns"] not in plan["missing_times"],
                       "candidate_count": len(plan["raw"][g["epoch_index"]]),
                       "eligible_count": sum(r["eligible"] == "True" for r in plan["raw"][g["epoch_index"]])} for g in plan["grid"]])
        plan["dop_recording"] = config["runtime"].get("dop_recording", True)
        results, terms, calls = engine.execute_measurements(plan, out)
        obs_sha, nav_sha = provenance["obs_sha256"], engine.sha(inputs["nav"])
        for r in results:
            r.update(dataset_id="UrbanNav-HK-Medium-Urban-1/ublox.f9p.splitter/GPS-C1C/"+obs_sha,
                     obs_sha256=obs_sha, nav_sha256=nav_sha,
                     source_result_id=f"native-window:{out.parent.name}/{r['method']}/{r['gps_ns']}")
        engine.dump(out/"fresh_results.json", results)
        table(engine, out/"fresh_satellite_terms.csv", terms, ["method", "epoch_index", "sv"])
        quals = qualify(results, terms, plan, rules, provenance, inputs, out, engine, module)
        engine.write_csv(out/"epoch_qualification.csv", quals)
        summaries = {}
        for method in engine.METHODS:
            rr = [r for r in results if r["method"] == method]; qq = [q for q in quals if q["method"] == method]
            ms = [r["epoch_elapsed_ms"] for r in rr if r["solver_called"]]
            summaries[method] = {"method_id": engine.METHODS[method], "requested": len(rr),
                "OBS_matched": sum(r["obs_present"] for r in rr), "solver_calls": sum(r["solver_called"] for r in rr),
                "converged": sum(r["converged"] for r in rr), "accepted": sum(r["accepted"] for r in rr),
                "software_rejected_after_call": sum(r["solver_called"] and not r["accepted"] for r in rr),
                "not_called": sum(not r["solver_called"] for r in rr),
                "qualifications": {k: dict(Counter(q[k] for q in qq)) for k in module.FLAGS},
                "final_classes": dict(Counter(q["FINAL_STATE"] for q in qq)),
                "epoch_elapsed_ms": {"minimum": min(ms) if ms else None, "maximum": max(ms) if ms else None,
                                     "mean": sum(ms)/len(ms) if ms else None}}
        summary = {"mode": MODE, "adapter_version": VERSION, "requested_slots": len(plan["grid"]),
            "OBS_matched": len(plan["grid"])-len(plan["missing_times"]), "missing_times": plan["missing_times"],
            "parsed_OBS_epochs": provenance["parsed_epoch_count"], "OBS_semantic_parse_passes": 1,
            "top_level_calls": sum(c["top_level"] for c in calls), "NAV_setups": len(engine.METHODS),
            "FDE_internal_candidate_fits": sum(c["FDE_internal_candidate_fits"] for c in calls),
            "set_epoch_satposs_calls": sum(c["set_epoch_satposs"] for c in calls), "calls": calls,
            "model_rows": len(terms), "methods": summaries, "runtime_elapsed_seconds": time.perf_counter()-started,
            "P95_recomputed": False, "real_navigation_effective_ratio": None, "peak_memory": "NOT_MEASURED"}
        engine.dump(out/"window_summary.json", summary)
        sealed_names = ["fresh_results.json", "fresh_satellite_terms.csv", "epoch_qualification.csv", "window_summary.json", "requested_slots.json", "native_gps_fields.csv", "native_obs_provenance.json", "effective_rules.json"]
        engine.dump(out/"runtime_outputs_seal.json", {"files": {n: engine.sha(out/n) for n in sealed_names},
            "runtime_complete": True, "history_read_before_seal": False})
        engine.progress(out, "OPTIONAL_COMPARISON")
        comparison = optional_comparison(config, out, config_path.parent, engine)
        engine.dump(out/"historical_comparison.json", comparison)
        engine.dump(out/"runtime_completion.json", {"comparison_equal": comparison["all_equal"], "runtime_complete": True,
            "comparison_status": comparison["status"], "history_required_for_navigation": False})
        engine.progress(out, "COMPLETED")
        print(json.dumps({"runtime_complete": True, "top_level_calls": summary["top_level_calls"], "comparison_status": comparison["status"]}))
        return 3 if comparison["all_equal"] is False else 0
    finally:
        engine.dump(out/"read_access_log.json", {"scope": "Python open audit and ctypes DLL load in window stage; native DLL file I/O not traced",
                                              "events": accesses})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Compare an already sealed window; never solve navigation.")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    import importlib.util
    spec = importlib.util.spec_from_file_location("e5_comparison_engine", Path(__file__).with_name("replay_urbannav.py"))
    e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)
    if a.output.exists() or not a.output.parent.is_dir():
        raise SystemExit("comparison output must be a new file in an existing directory")
    result = optional_comparison(e.load(a.config), a.run_dir, a.config.parent, e)
    e.dump(a.output, result)
    print(json.dumps(result))
    raise SystemExit(3 if result["all_equal"] is False else 0)
