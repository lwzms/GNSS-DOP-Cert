"""Materialize local paths from a verified package; never runs navigation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def runner_at(root):
    spec = importlib.util.spec_from_file_location("baseline_configuration_runner", root/"tools/experiments/run_frozen_analysis.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def prepare(root, external_paths, python, output_root, destination):
    root, destination, output_root = root.resolve(), destination.resolve(), output_root.resolve()
    runner = runner_at(root)
    snapshot = runner.read_snapshot(root, root/"SOURCE_MANIFEST.json")
    dependencies = runner.load_json(root/"EXTERNAL_DEPENDENCIES.json")
    config = runner.load_json(root/"configs/baseline_runtime.template.json")
    if destination.exists():
        raise ValueError("LOCAL_CONFIG_EXISTS: choose a new file")
    if output_root == root or output_root.is_relative_to(root):
        raise ValueError("RUN_OUTPUT_MUST_BE_OUTSIDE_PACKAGE")
    if not python.is_file():
        raise ValueError(f"PYTHON_MISSING: {python}")
    for name in ("obs", "nav", "dll"):
        path = external_paths[name].resolve()
        info = runner.identity(path, dependencies["files"][name]["sha256"])
        if info["size_bytes"] != dependencies["files"][name]["size_bytes"]:
            raise ValueError(f"EXTERNAL_SIZE_MISMATCH: {name}")
    base = destination.parent
    rel = lambda path: Path(os.path.relpath(path, base)).as_posix()
    files = {r["path"]: r for r in runner.load_json(root/"SOURCE_MANIFEST.json")["files"]}
    config["code_identity"] = {"mode": "SNAPSHOT", "root": rel(root),
        "manifest": rel(root/"SOURCE_MANIFEST.json"), "manifest_sha256": snapshot["manifest"]["sha256"],
        "snapshot_id": snapshot["snapshot_id"]}
    config["e0"]["directory"] = rel(root/"provenance/e0")
    runtime = config["runtime"]
    runtime.update(source_root=rel(root), python=str(python.resolve()), output_root=str(output_root),
                   execution_working_directory=rel(root),
                   protected_roots=sorted({str(p.resolve().parent) for p in external_paths.values()}))
    for key in ("obs", "nav", "dll"):
        runtime[key] = {"path": str(external_paths[key].resolve()), "sha256": dependencies["files"][key]["sha256"]}
    names = {"rules": "configs/experiments/runtime/urbannav_final_residual_rules_v1.json",
             "A": "configs/experiments/runtime/urbannav_spp_A.conf", "B": "configs/experiments/runtime/urbannav_spp_B.conf"}
    runtime["rules"] = {"path": rel(root/names["rules"]), "sha256": files[names["rules"]]["sha256"]}
    runtime["scientific_configs"] = {k: {"path": rel(root/names[k]), "sha256": files[names[k]]["sha256"]} for k in ("A", "B")}
    runtime["entry"].update(script="tools/experiments/replay_urbannav.py",
        sha256=files["tools/experiments/replay_urbannav.py"]["sha256"],
        module=rel(root/"src/gnss_toolbox/evaluation/saved_qualification.py"),
        module_sha256=files["src/gnss_toolbox/evaluation/saved_qualification.py"]["sha256"])
    runtime["code_snapshots"] = [{"source": name, "destination": "code/"+name,
        "sha256": row["sha256"], "role": "packaged_runtime_source"} for name, row in files.items()
        if ((name.startswith("tools/") or name.startswith("src/")) and name.endswith(".py")) or name in names.values()]
    config["comparison"] = {"enabled": False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf8") as h:
        h.write(json.dumps(config, ensure_ascii=False, indent=2)+"\n")
    return destination


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("obs", "nav", "dll", "output-root", "config"):
        p.add_argument("--"+key, type=Path, required=True)
    p.add_argument("--python", type=Path, default=Path(sys.executable))
    a = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    path = prepare(root, {k: getattr(a, k) for k in ("obs", "nav", "dll")}, a.python, a.output_root, a.config)
    print(json.dumps({"local_config": str(path), "navigation_calls": 0}))
