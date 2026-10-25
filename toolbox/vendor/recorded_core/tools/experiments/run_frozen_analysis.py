"""Run one explicitly selected analysis, qualification or bounded GNSS replay.

The reviewed RETURN08 script is unchanged. This is a process/identity boundary,
not an OS sandbox for arbitrary scripts or untrusted configurations.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import uuid


class Blocked(Exception):
    """Explicit boundary failure, including under Python optimization."""


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(path, expected=None):
    if not path.is_file():
        raise Blocked(f"INPUT_MISSING: {path}")
    item = {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha(path)}
    if expected is not None and item["sha256"] != expected:
        raise Blocked(f"INPUT_SHA256_MISMATCH: {path}")
    return item


def load_json(path):
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def save_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
    temporary.replace(path)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise Blocked(f"CONFIG_INVALID: {name} must be nonempty text")
    return value


def resolved(value, base):
    p = Path(text(value, "path"))
    return (p if p.is_absolute() else base / p).resolve()


def relative(value):
    value = text(value, "workspace path")
    p = PurePosixPath(value)
    if "\\" in value or ":" in value or p.is_absolute() or ".." in p.parts or str(p) != value or value == ".":
        raise Blocked(f"CONFIG_INVALID_WORKSPACE_PATH: {value}")
    return Path(*p.parts)


def expected(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise Blocked("CONFIG_INVALID: expected SHA256 must have 64 lowercase hexadecimal characters")
    return value


def git_state(path):
    def query(*args):
        return subprocess.check_output(["git", "-c", "core.quotepath=false", "-C", str(path), *args],
                                       text=True, encoding="utf8", stderr=subprocess.PIPE, timeout=10).strip()
    try:
        return {"root": query("rev-parse", "--show-toplevel"), "head": query("rev-parse", "HEAD"),
                "branch": query("branch", "--show-current"),
                "working_tree_status": query("status", "--porcelain=v1", "--untracked-files=all")}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"head": "UNKNOWN", "working_tree_status": "UNKNOWN", "reason": str(exc)}


def read_snapshot(root, manifest_path, expected_sha=None):
    """Verify every packaged file; the manifest excludes itself to avoid a cycle."""
    root, manifest_path = root.resolve(), manifest_path.resolve()
    if not manifest_path.is_relative_to(root) or (root / ".git").exists():
        raise Blocked("SNAPSHOT_ROOT_OR_GIT_MODE_CONFLICT")
    manifest_identity = identity(manifest_path, expected_sha)
    manifest = load_json(manifest_path)
    files = manifest["files"]
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf8")
    snapshot_id = "GNSS118-E17-CORE-" + hashlib.sha256(canonical).hexdigest()
    if manifest.get("snapshot_id") != snapshot_id:
        raise Blocked("SNAPSHOT_ID_MISMATCH")
    seen, identities = set(), []
    for row in files:
        rel = relative(row["path"])
        key = rel.as_posix().casefold()
        path = (root / rel).resolve()
        if key in seen or not path.is_relative_to(root) or path == manifest_path:
            raise Blocked("SNAPSHOT_MANIFEST_PATH_INVALID")
        seen.add(key)
        item = identity(path, expected(row["sha256"]))
        if item["size_bytes"] != row["size_bytes"]:
            raise Blocked("SNAPSHOT_SIZE_MISMATCH")
        identities.append({**item, "role": "snapshot_package_file", "destination": None})
    for path in root.rglob("*.py"):
        if path.relative_to(root).as_posix().casefold() not in seen:
            raise Blocked(f"UNLISTED_SNAPSHOT_CODE: {path}")
    return {"identity_source": "SOURCE_SNAPSHOT", "root": str(root), "snapshot_id": snapshot_id,
            "baseline_id": manifest["baseline_id"], "manifest": manifest_identity,
            "head": None, "branch": None, "working_tree_status": "NOT_APPLICABLE_NO_GIT",
            "origin_scientific_commit": manifest["origin_scientific_commit"],
            "files": identities}


def code_identity(config, base, wrapper):
    spec = config.get("code_identity", {"mode": "GIT"})
    if not isinstance(spec, dict):
        raise Blocked("INVALID_CODE_IDENTITY_MODE")
    if spec.get("mode") == "GIT":
        if any(k in spec for k in ("root", "manifest", "snapshot_id", "manifest_sha256")):
            raise Blocked("GIT_SNAPSHOT_IDENTITY_MIXED")
        return {"identity_source": "GIT", **git_state(wrapper.parent)}
    if spec.get("mode") != "SNAPSHOT":
        raise Blocked("INVALID_CODE_IDENTITY_MODE")
    root = resolved(spec["root"], base)
    info = read_snapshot(root, resolved(spec["manifest"], base), expected(spec["manifest_sha256"]))
    if info["snapshot_id"] != spec["snapshot_id"] or not wrapper.is_relative_to(root):
        raise Blocked("SNAPSHOT_WRAPPER_OR_ID_MISMATCH")
    if str(wrapper) not in {v["path"] for v in info["files"]}:
        raise Blocked("SNAPSHOT_WRAPPER_NOT_LISTED")
    return info


def runtime_view(config):
    """Normalize only runtime inputs; never inspect comparison file descriptors."""
    if "runtime" not in config:
        return config, False
    if any(k in config for k in ("analysis", "replay", "qualification", "source_results", "inputs", "read_only_inputs")):
        raise Blocked("CONFIG_AMBIGUOUS_RUNTIME")
    runtime = config["runtime"]
    if not isinstance(runtime, dict) or runtime.get("mode") != "NATIVE_OBS_WINDOW_V1":
        raise Blocked("UNSUPPORTED_RUNTIME_MODE")
    comparison = config.get("comparison", {})
    if not isinstance(comparison, dict) or type(comparison.get("enabled", False)) is not bool:
        raise Blocked("CONFIG_INVALID_COMPARISON_SWITCH")
    view = {**config, "source_results": runtime["source_root"], "analysis": runtime["entry"],
            "python": runtime["python"], "output_root": runtime["output_root"],
            "timeout_seconds": runtime["timeout_seconds"], "dependencies": runtime.get("dependencies", ["numpy"]),
            "protected_roots": runtime["protected_roots"], "comparisons": [],
            "inputs": list(runtime["code_snapshots"]), "read_only_inputs": []}
    for role, item in [(k, runtime[k]) for k in ("obs", "nav", "dll", "rules")] + [
            ("scientific_config_"+k, runtime["scientific_configs"][k]) for k in ("A", "B")]:
        view["read_only_inputs"].append({"source": item["path"], "sha256": item["sha256"], "role": "runtime_"+role})
    if runtime.get("reference_contract") is not None:
        item = runtime["reference_contract"]
        view["read_only_inputs"].append({"source": item["path"], "sha256": item["sha256"], "role": "runtime_reference_contract"})
    return view, True


def plan(config_path, run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", run_id) or run_id.endswith("."):
        raise Blocked("INVALID_RUN_ID")
    if run_id.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise Blocked("INVALID_RUN_ID")
    config = load_json(config_path)
    if not isinstance(config, dict) or config.get("version") != 1:
        raise Blocked("CONFIG_INVALID_VERSION")
    config, window_stage = runtime_view(config)
    base = config_path.parent
    experiment_id = text(config.get("experiment_id"), "experiment_id")
    e0 = config["e0"]
    freeze_id = text(e0["freeze_id"], "e0.freeze_id")
    e0_path = resolved(e0["directory"], base)
    source = resolved(config["source_results"], base)
    qualification = config.get("qualification", {})
    if not isinstance(qualification, dict) or type(qualification.get("enabled", False)) is not bool:
        raise Blocked("CONFIG_INVALID_QUALIFICATION_SWITCH")
    qualified_stage = qualification.get("enabled", False)
    replay = config.get("replay", {})
    if not isinstance(replay, dict) or type(replay.get("enabled", False)) is not bool:
        raise Blocked("CONFIG_INVALID_REPLAY_SWITCH")
    replay_stage = replay.get("enabled", False)
    if replay_stage:
        if qualified_stage or config.get("analysis") is not None:
            raise Blocked("CONFIG_AMBIGUOUS_STAGE")
        if ((replay.get("adapter_id"), replay.get("protocol_id")) != ("URBANNAV_REAL_REPLAY_V1", "URBANNAV_GPS_C1C_EVAL_V1")
                or replay.get("input_mode") not in ("PINNED_C1C_EXCERPT_V1", "NATIVE_RINEX_C1C_V1")):
            raise Blocked("UNSUPPORTED_REPLAY_ADAPTER")
        if replay.get("indices") != [0, 548, 785] or replay.get("comparison_policy") != "EXACT_REPLAY_SCIENCE_V1":
            raise Blocked("UNSUPPORTED_REPLAY_SELECTION_OR_COMPARISON")
    if qualified_stage:
        if config.get("analysis") is not None:
            raise Blocked("CONFIG_AMBIGUOUS_STAGE: use one explicitly selected adapter per run")
        if (qualification.get("adapter_id"), qualification.get("protocol_id"), qualification.get("input_mode")) != (
                "URBANNAV_SAVED_P95_V1", "URBANNAV_GPS_C1C_EVAL_V1", "SAVED_P95_RECORDS_V1"):
            raise Blocked("UNSUPPORTED_QUALIFICATION_ADAPTER")
    analysis = replay if replay_stage else qualification if qualified_stage else config["analysis"]
    script = resolved(analysis["script"], source)
    python = resolved(config["python"], base)
    output_root = resolved(config["output_root"], base)
    target = (output_root / run_id).resolve()
    if target.parent != output_root:
        raise Blocked("OUTPUT_PATH_ESCAPES_ROOT")
    duration = config["timeout_seconds"]
    if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or not 0 < duration <= 3600:
        raise Blocked("CONFIG_INVALID_TIMEOUT")
    inputs = config["inputs"]
    comparisons = config["comparisons"]
    readonly = config.get("read_only_inputs", [])
    protected = config["protected_roots"]
    if not all(isinstance(a, list) for a in [inputs, comparisons, readonly, protected]) or not inputs or (not comparisons and not (qualified_stage or replay_stage or window_stage)) or not protected:
        raise Blocked("CONFIG_INVALID_ARTIFACT_LISTS")
    artifacts = []
    destinations = set()
    for row in inputs:
        dest = relative(row["destination"])
        key = str(dest).casefold()
        if key in destinations:
            raise Blocked("CONFIG_DUPLICATE_DESTINATION")
        destinations.add(key)
        artifacts.append({"path": resolved(row["source"], source), "expected": expected(row["sha256"]),
                          "role": text(row["role"], "input.role"), "destination": dest})
    for row in readonly:
        artifacts.append({"path": resolved(row["source"], base), "expected": expected(row["sha256"]),
                          "role": text(row["role"], "read_only.role"), "destination": None})
    checks = []
    for row in comparisons:
        actual = relative(row["actual"])
        if str(actual).casefold() in destinations or row["kind"] not in ["json_exact", "csv_exact"]:
            raise Blocked("CONFIG_INVALID_COMPARISON")
        path = resolved(row["expected"], source)
        checks.append({"expected": path, "sha256": expected(row["sha256"]), "actual": actual, "kind": row["kind"]})
        artifacts.append({"path": path, "expected": expected(row["sha256"]), "role": "comparison_reference", "destination": None})
    artifacts += [{"path": script, "expected": expected(analysis["sha256"]), "role": "analysis_script", "destination": None},
                  {"path": e0_path / "FREEZE_README_E0.md", "expected": expected(e0["readme_sha256"]), "role": "e0_readme", "destination": None},
                  {"path": e0_path / "FILE_MANIFEST_E0.csv", "expected": expected(e0["file_manifest_sha256"]), "role": "e0_manifest", "destination": None}]
    qualification_module = None
    if qualified_stage or replay_stage or window_stage:
        qualification_module = resolved(analysis["module"], base)
        artifacts.append({"path": qualification_module, "expected": expected(analysis["module_sha256"]),
                          "role": "qualification_module", "destination": None})
    forbidden = [e0_path, source, *[resolved(v, base) for v in protected], *[a["path"].parent for a in artifacts]]
    if any(target == p or target.is_relative_to(p) or output_root == p or output_root.is_relative_to(p) for p in forbidden):
        raise Blocked("OUTPUT_PATH_PROTECTED")
    args = analysis["arguments"]
    if not isinstance(args, list) or not all(isinstance(v, str) for v in args) or "{analysis_dir}" not in args:
        raise Blocked("CONFIG_INVALID_ARGUMENTS")
    if qualified_stage and not all(v in args for v in ["{qualification_dir}", "{qualification_module}"]):
        raise Blocked("CONFIG_INVALID_QUALIFICATION_ARGUMENTS")
    if (replay_stage or window_stage) and not all(v in args for v in ["{replay_dir}", "{qualification_module}", "{config_file}"]):
        raise Blocked("CONFIG_INVALID_REPLAY_ARGUMENTS")
    analysis_dir = relative(analysis["directory"])
    dependencies = config.get("dependencies", ["numpy"])
    if not isinstance(dependencies, list) or not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", v) for v in dependencies):
        raise Blocked("CONFIG_INVALID_DEPENDENCIES")
    return {"config": config, "experiment_id": experiment_id, "freeze_id": freeze_id, "source": source,
            "script": script, "python": python, "output_root": output_root, "target": target,
            "analysis_dir": analysis_dir, "arguments": args, "timeout": duration,
            "artifacts": artifacts, "checks": checks, "dependencies": dependencies, "e0_path": e0_path,
            "qualification_enabled": qualified_stage, "qualification_module": qualification_module,
            "replay_enabled": replay_stage, "window_enabled": window_stage}


def environment(python, dependencies):
    code = ("import sys,json,importlib.metadata as m; "
            f"print(json.dumps({{'path':sys.executable,'version':sys.version,'dependencies':{{n:m.version(n) for n in {dependencies!r}}}}}))")
    completed = subprocess.run([str(python), "-I", "-B", "-X", "utf8", "-c", code],
                               capture_output=True, text=True, encoding="utf8", timeout=15, check=True)
    return json.loads(completed.stdout)


def preflight(p):
    if not p["python"].is_file():
        raise Blocked("PYTHON_NOT_FOUND")
    identities = []
    for a in p["artifacts"]:
        identities.append({**identity(a["path"], a["expected"]), "role": a["role"],
                           "destination": str(a["destination"]) if a["destination"] is not None else None})
    if p["freeze_id"] not in (p["e0_path"] / "FREEZE_README_E0.md").read_text(encoding="utf8"):
        raise Blocked("E0_FREEZE_ID_MISMATCH")
    return identities, environment(p["python"], p["dependencies"])


def compare(p, work):
    rows = []
    for item in p["checks"]:
        output = work / item["actual"]
        row = {"actual": str(output), "reference": str(item["expected"]), "kind": item["kind"],
               "policy": "all parsed values/cells exact; no ignored fields; no float tolerance"}
        if output.is_file():
            if item["kind"] == "json_exact":
                a, b = load_json(output), load_json(item["expected"])
            else:
                with output.open(encoding="utf-8-sig", newline="") as f:
                    a = list(csv.reader(f))
                with item["expected"].open(encoding="utf-8-sig", newline="") as f:
                    b = list(csv.reader(f))
            equal = json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)
            row.update({"equal": equal, "actual_sha256": sha(output), "reference_sha256": sha(item["expected"])})
            if not equal:
                row["actual_values"], row["reference_values"] = a, b
        else:
            row.update({"equal": False, "reason": "OUTPUT_MISSING"})
        rows.append(row)
    return {"policy": "EXACT_JSON_VALUES_AND_CSV_CELLS_V1", "all_equal": all(r["equal"] for r in rows), "files": rows}


def run(config_path, run_id, dry_run=False):
    started, tick = stamp(), time.perf_counter()
    config_path = config_path.resolve()
    p = None
    directory = None
    before = []
    meta = {"run_id": run_id, "started_at": started, "status": "INPUT_BLOCKED", "phase": "CONFIG",
            "exit_code": None, "wrapper_exit_code": 2, "peak_memory": "NOT_MEASURED", "child_started": False,
            "experiment_id": "UNKNOWN", "e0_freeze_id": "UNKNOWN", "inputs": [], "command": None,
            "python": None, "working_directory": None, "output_directory": None, "time_limit_seconds": None,
            "wrapper_python": {"path": sys.executable, "version": sys.version},
            "dependency_probe_limit_seconds": 15,
            "dry_run": dry_run, "scope": "existing result analysis only; E1 status is not navigation/model/reference validity"}
    try:
        meta["configuration"] = identity(config_path)
        meta["wrapper"] = identity(Path(__file__).resolve())
        meta["code"] = code_identity(load_json(config_path), config_path.parent, Path(__file__).resolve())
        p = plan(config_path, run_id)
        snapshot = meta["code"]["identity_source"] == "SOURCE_SNAPSHOT"
        if snapshot and str(p["script"]) not in {v["path"] for v in meta["code"]["files"]}:
            raise Blocked("SNAPSHOT_ENTRY_NOT_LISTED")
        meta.update({"experiment_id": p["experiment_id"], "e0_freeze_id": p["freeze_id"],
                     "time_limit_seconds": p["timeout"], "requested_output": str(p["target"]),
                     "source_code": ({k:v for k,v in meta["code"].items() if k != "files"} if snapshot else
                                     {"identity_source": "GIT", **git_state(p["script"].parent)}), "resolved_configuration": p["config"],
                     "input_plan": [{"path": str(a["path"]), "role": a["role"], "expected_sha256": a["expected"]} for a in p["artifacts"]]})
        if p["target"].exists():
            if not dry_run:
                directory = p["output_root"] / "_rejections" / (run_id + "-" + uuid.uuid4().hex)
                directory.mkdir(parents=True, exist_ok=False)
            raise Blocked("RUN_ID_EXISTS: no existing run files were touched")
        if not dry_run:
            p["target"].parent.mkdir(parents=True, exist_ok=True)
            p["target"].mkdir(exist_ok=False)
            directory = p["target"]
            (directory / "stdout.log").touch(exist_ok=False)
            (directory / "stderr.log").touch(exist_ok=False)
            save_json(directory / "run_metadata.json", meta)
        meta["phase"] = "PREFLIGHT"
        before, env = preflight(p)
        if snapshot:
            before += meta["code"]["files"] + [{**meta["code"]["manifest"], "role": "snapshot_manifest", "destination": None}]
        before += [{**meta["configuration"], "role": "configuration", "destination": None},
                   {**meta["wrapper"], "role": "wrapper", "destination": None}]
        meta.update({"inputs": before, "python": env, "analysis_script": identity(p["script"]),
                     "comparison_policy": "EXACT_JSON_VALUES_AND_CSV_CELLS_V1"})
        if p["qualification_enabled"]:
            meta.update({"qualification": {"enabled": True, "adapter_id": p["config"]["qualification"]["adapter_id"],
                         "protocol_id": p["config"]["qualification"]["protocol_id"],
                         "input_mode": p["config"]["qualification"]["input_mode"],
                         "module": identity(p["qualification_module"])},
                         "comparison_policy": "EXACT_DISCRETE_FLAGS_IDENTITY_CHECKS_REASONS_AND_COUNTS_V1"})
        if p["replay_enabled"]:
            meta.update({"replay": {"enabled": True, "adapter_id": p["config"]["replay"]["adapter_id"],
                         "input_mode": p["config"]["replay"]["input_mode"], "indices": p["config"]["replay"]["indices"],
                         "module": identity(p["qualification_module"])}, "comparison_policy": "EXACT_REPLAY_SCIENCE_V1",
                         "scope": "six explicit UrbanNav navigation calls then post-classification; no accuracy certification"})
        if p["window_enabled"]:
            meta.update({"runtime_mode": "NATIVE_OBS_WINDOW_V1", "comparison_enabled": p["config"].get("comparison", {}).get("enabled", False),
                         "comparison_policy": "OPTIONAL_AFTER_RUNTIME_SEAL",
                         "scope": "configured native-OBS navigation and post-qualification; optional historical comparison"})
        if dry_run:
            meta.update({"status": "DRY_RUN_READY", "wrapper_exit_code": 0})
            return meta
        work = directory / "work"
        work.mkdir()
        (work / p["analysis_dir"]).mkdir(parents=True, exist_ok=True)
        copies = []
        for a in p["artifacts"]:
            if a["destination"] is None:
                continue
            target = work / a["destination"]
            target.parent.mkdir(parents=True, exist_ok=True)
            with a["path"].open("rb") as src, target.open("xb") as dest:
                shutil.copyfileobj(src, dest)
            copies.append({"source": str(a["path"]), "role": a["role"], **identity(target, a["expected"])})
        meta["copies"] = copies
        args = [v.replace("{analysis_dir}", str(work / p["analysis_dir"])) for v in p["arguments"]]
        if p["qualification_enabled"]:
            args = [v.replace("{qualification_dir}", str(directory / "qualification")).replace(
                "{qualification_module}", str(p["qualification_module"])) for v in args]
        if p["replay_enabled"] or p["window_enabled"]:
            args = [v.replace("{replay_dir}", str(directory / "replay")).replace(
                "{qualification_module}", str(p["qualification_module"])).replace("{config_file}", str(config_path)) for v in args]
        command = [str(p["python"]), "-I", "-B", "-X", "utf8", str(p["script"]), *args]
        child_cwd = work
        requested_cwd = p["config"].get("runtime", {}).get("execution_working_directory")
        if requested_cwd is not None:
            child_cwd = resolved(requested_cwd, config_path.parent)
            if not snapshot or not child_cwd.is_dir() or not child_cwd.is_relative_to(Path(meta["code"]["root"])):
                raise Blocked("SNAPSHOT_EXECUTION_DIRECTORY_INVALID")
        meta.update({"command": command, "working_directory": str(child_cwd), "status": "RUNNING", "phase": "SUBPROCESS"})
        save_json(directory / "run_metadata.json", meta)
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=child_cwd, stdout=stdout, stderr=stderr, shell=False)
            meta["child_started"] = True
            try:
                meta["exit_code"] = process.wait(timeout=p["timeout"])
            except subprocess.TimeoutExpired:
                process.kill()
                meta["exit_code"] = process.wait()
                meta.update({"status": "TIMED_OUT", "wrapper_exit_code": 124, "reason": "SUBPROCESS_TIMEOUT"})
        if meta["status"] != "TIMED_OUT":
            if meta["exit_code"]:
                meta.update({"status": "FAILED", "wrapper_exit_code": 1, "reason": "SOURCE_SCRIPT_EXIT_NONZERO"})
                if p["qualification_enabled"] and meta["exit_code"] == 3:
                    meta["reason"] = "QUALIFICATION_REGRESSION_MISMATCH"
                if p["qualification_enabled"] and meta["exit_code"] == 2:
                    meta.update({"status": "INPUT_BLOCKED", "wrapper_exit_code": 2, "reason": "QUALIFICATION_INPUT_BLOCKED"})
                if (p["replay_enabled"] or p["window_enabled"]) and meta["exit_code"] in (2, 3):
                    meta.update({"status": "INPUT_BLOCKED" if meta["exit_code"] == 2 else "FAILED",
                                 "wrapper_exit_code": 2 if meta["exit_code"] == 2 else 1,
                                 "reason": "REPLAY_INPUT_BLOCKED" if meta["exit_code"] == 2 else "REPLAY_COMPARISON_MISMATCH"})
            else:
                meta["phase"] = "COMPARISON"
                comparison = (load_json(directory / "replay/runtime_completion.json") if p["window_enabled"] else
                              load_json(directory / "replay/replay_comparison.json") if p["replay_enabled"] else
                              load_json(directory / "qualification/qualification_comparison.json") if p["qualification_enabled"] else compare(p, work))
                if p["window_enabled"]:
                    if comparison.get("runtime_complete") is not True or comparison.get("comparison_status") not in ("NOT_RUN", "MATCHED", "MISMATCH"):
                        raise ValueError("INVALID_RUNTIME_COMPLETION")
                    ok = comparison["comparison_status"] != "MISMATCH"
                    meta.update({"status": "SUCCEEDED" if ok else "FAILED", "wrapper_exit_code": 0 if ok else 1,
                                 "reason": "RUNTIME_COMPLETED_COMPARISON_"+comparison["comparison_status"]})
                else:
                    if type(comparison.get("all_equal")) is not bool:
                        raise ValueError("INVALID_COMPARISON_RESULT")
                    meta.update({"status": "SUCCEEDED" if comparison["all_equal"] else "FAILED",
                                 "wrapper_exit_code": 0 if comparison["all_equal"] else 1,
                                 "reason": "EXACT_RESULTS_MATCH" if comparison["all_equal"] else "SCIENTIFIC_RESULT_MISMATCH"})
                save_json(directory / "result_comparison.json", comparison)
        if p["replay_enabled"] or p["window_enabled"]:
            for receipt_name in ("execution_progress.json", "failure_receipt.json"):
                receipt_path = directory / "replay" / receipt_name
                if receipt_path.is_file():
                    receipt = load_json(receipt_path)
                    meta[receipt_name.removesuffix(".json")] = receipt
                    if receipt_name == "failure_receipt.json":
                        meta["failure_stage"] = receipt["failure_stage"]
                        if receipt.get("top_level_started", 0) > 0 and meta["status"] != "TIMED_OUT":
                            meta.update(status="FAILED", wrapper_exit_code=1, reason="REPLAY_POST_SOLVE_FAILURE")
        copied_changes = [r["path"] for r in copies if not Path(r["path"]).is_file() or sha(Path(r["path"])) != r["sha256"]]
        meta["copied_inputs_unchanged"] = not copied_changes
        if copied_changes:
            meta.update({"status": "FAILED", "wrapper_exit_code": 1, "reason": "COPIED_INPUT_CHANGED", "changed_copies": copied_changes})
    except Blocked as exc:
        meta.update({"status": "INPUT_BLOCKED", "reason": str(exc), "wrapper_exit_code": 2})
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        meta.update({"status": "FAILED" if meta["child_started"] else "INPUT_BLOCKED", "reason": type(exc).__name__ + ": " + str(exc),
                     "wrapper_exit_code": 1 if meta["child_started"] else 2})
    finally:
        if before:
            changes = []
            for r in before:
                path = Path(r["path"])
                if not path.is_file() or sha(path) != r["sha256"]:
                    changes.append(str(path))
            meta["original_inputs_unchanged"] = not changes
            meta["changed_original_inputs"] = changes
            if changes:
                meta.update({"status": "FAILED", "wrapper_exit_code": 1, "reason": "ORIGINAL_INPUT_CHANGED"})
        meta.update({"ended_at": stamp(), "elapsed_seconds": time.perf_counter() - tick})
        if directory is not None:
            for name in ["stdout.log", "stderr.log"]:
                (directory / name).touch(exist_ok=True)
            if meta["status"] not in {"SUCCEEDED", "DRY_RUN_READY"}:
                with (directory / "stderr.log").open("a", encoding="utf8") as handle:
                    handle.write("\n" + json.dumps({"wrapper_status": meta["status"], "phase": meta["phase"], "reason": meta.get("reason")}, ensure_ascii=False) + "\n")
            meta["output_directory"] = str(directory)
            meta["outputs"] = [identity(f) for f in sorted(directory.rglob("*")) if f.is_file() and f.name not in {"run_metadata.json", "run_metadata.json.tmp"}]
            save_json(directory / "run_metadata.json", meta)
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(args.config, args.run_id, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), file=sys.stdout if result["wrapper_exit_code"] == 0 else sys.stderr)
    return result["wrapper_exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
