"""Package/path/identity tests; no navigation is invoked by pytest."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


r = module("snapshot_tests_runner", ROOT/"tools/experiments/run_frozen_analysis.py")
helper = module("snapshot_tests_configurer", ROOT/"tools/experiments/prepare_baseline_config.py")


def seal(root):
    files = [{"path": p.relative_to(root).as_posix(), "size_bytes": p.stat().st_size,
              "sha256": r.sha(p)} for p in sorted(root.rglob('*')) if p.is_file() and p.name != "SOURCE_MANIFEST.json"]
    sid = "GNSS118-A-RC1-"+hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    data = {"baseline_id": "GNSS118_A_ENGINEERING_BASELINE_RC1", "snapshot_id": sid,
            "origin_scientific_commit": "60535f0f7592489e4b9592891e7a071d2f7f50e0", "files": files}
    (root/"SOURCE_MANIFEST.json").write_text(json.dumps(data), encoding="utf8")
    return data


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path/"package"; root.mkdir(); (root/"tool.py").write_text("value=1\n")
    data = seal(root)
    spec = {"code_identity": {"mode": "SNAPSHOT", "root": str(root), "manifest": str(root/"SOURCE_MANIFEST.json"),
                             "manifest_sha256": r.sha(root/"SOURCE_MANIFEST.json"), "snapshot_id": data["snapshot_id"]}}
    return root, data, spec


def test_snapshot_identity_has_no_current_git_head(snapshot, monkeypatch):
    root, data, config = snapshot
    monkeypatch.setattr(r, "git_state", lambda path: (_ for _ in ()).throw(AssertionError("Git was queried")))
    result = r.code_identity(config, root, root/"tool.py")
    assert result["identity_source"] == "SOURCE_SNAPSHOT" and result["head"] is None
    assert result["branch"] is None and result["snapshot_id"] == data["snapshot_id"]
    assert result["origin_scientific_commit"] == "60535f0f7592489e4b9592891e7a071d2f7f50e0"


@pytest.mark.parametrize("kind", ["changed", "missing", "unlisted", "git", "wrong-id", "wrong-manifest-sha"])
def test_snapshot_checks_are_not_disabled(snapshot, kind):
    root, data, config = snapshot
    if kind == "changed": (root/"tool.py").write_text("value=2\n")
    if kind == "missing": (root/"tool.py").unlink()
    if kind == "unlisted": (root/"extra.py").write_text("extra=True\n")
    if kind == "git": (root/".git").write_text("gitdir: elsewhere\n")
    if kind == "wrong-id": config["code_identity"]["snapshot_id"] = "wrong"
    if kind == "wrong-manifest-sha": config["code_identity"]["manifest_sha256"] = "0"*64
    with pytest.raises(r.Blocked):
        r.code_identity(config, root, root/"tool.py")


def test_git_mode_rejects_snapshot_fields(snapshot):
    root, _, config = snapshot; config["code_identity"]["mode"] = "GIT"
    with pytest.raises(r.Blocked, match="MIXED"):
        r.code_identity(config, root, root/"tool.py")
    git = r.code_identity({"code_identity": {"mode": "GIT"}}, root, Path(__file__))
    assert git["identity_source"] == "GIT" and "snapshot_id" not in git


def test_snapshot_manifest_paths_cannot_escape(snapshot):
    root, data, _ = snapshot
    data["files"][0]["path"] = "../outside.py"
    canonical = json.dumps(data["files"], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    data["snapshot_id"] = "GNSS118-A-RC1-"+hashlib.sha256(canonical).hexdigest()
    (root/"SOURCE_MANIFEST.json").write_text(json.dumps(data))
    with pytest.raises(r.Blocked, match="PATH"):
        r.read_snapshot(root, root/"SOURCE_MANIFEST.json")


@pytest.fixture
def tiny_package(tmp_path):
    root = tmp_path/"tiny"; (root/"tools/experiments").mkdir(parents=True)
    for name in ("run_frozen_analysis.py", "prepare_baseline_config.py"):
        shutil.copyfile(ROOT/"tools/experiments"/name, root/"tools/experiments"/name)
    for name in ("replay_urbannav.py",): (root/"tools/experiments"/name).write_text("# substitute entry, never executed\n")
    p = root/"src/gnss_toolbox/evaluation";p.mkdir(parents=True);(p/"saved_qualification.py").write_text("VERSION='test'\n")
    p = root/"configs/experiments/runtime";p.mkdir(parents=True)
    for name in ("urbannav_final_residual_rules_v1.json", "urbannav_spp_A.conf", "urbannav_spp_B.conf"): (p/name).write_text("test")
    e0 = root/"provenance/e0";e0.mkdir(parents=True)
    (e0/"FREEZE_README_E0.md").write_text("TEST_FREEZE_ID")
    (e0/"FILE_MANIFEST_E0.csv").write_text("path,sha256\n")
    c = {"version": 1, "experiment_id": "synthetic-package-boundary", "e0": {"freeze_id": "TEST_FREEZE_ID",
         "readme_sha256": r.sha(e0/"FREEZE_README_E0.md"), "file_manifest_sha256": r.sha(e0/"FILE_MANIFEST_E0.csv")},
         "runtime": {"mode": "NATIVE_OBS_WINDOW_V1", "timeout_seconds": 5, "dependencies": [],
         "entry": {"directory": "inputs", "arguments": ["--inputs", "{analysis_dir}", "--out", "{replay_dir}", "--config", "{config_file}", "--module", "{qualification_module}"]}}}
    (root/"configs/baseline_runtime.template.json").write_text(json.dumps(c))
    ext = {}; external_dir = tmp_path/"external-inputs"; external_dir.mkdir()
    for name in ("obs", "nav", "dll"):
        p = external_dir/(name+".input");p.write_bytes(b"synthetic external identity only");ext[name] = p
    (root/"EXTERNAL_DEPENDENCIES.json").write_text(json.dumps({"files": {k: {"sha256":r.sha(p),"size_bytes":p.stat().st_size} for k,p in ext.items()}}))
    seal(root)
    path = root/"local/runtime.json"
    helper.prepare(root, ext, Path(sys.executable), tmp_path/"runs", path)
    return root, ext, path


def test_materialized_config_preflights_without_git_or_history(tiny_package):
    root, ext, path = tiny_package
    runner = module("tiny_runner", root/"tools/experiments/run_frozen_analysis.py")
    config = runner.load_json(path)
    assert config["comparison"] == {"enabled":False}
    result = runner.run(path, "preflight", dry_run=True)
    assert result["status"] == "DRY_RUN_READY" and result["code"]["head"] is None
    assert result["code"]["identity_source"] == "SOURCE_SNAPSHOT"
    assert all("baseline_A.json" not in row["path"] for row in result["inputs"])
    with pytest.raises(ValueError, match="CONFIG_EXISTS"):
        helper.prepare(root, ext, Path(sys.executable), root.parent/"runs", path)


@pytest.mark.parametrize("kind", ["missing", "digest"])
def test_external_input_identity_is_required(tiny_package, kind):
    root, ext, path = tiny_package
    if kind == "missing": ext["nav"].unlink()
    else: ext["nav"].write_bytes(b"changed")
    runner = module("tiny_blocked_runner", root/"tools/experiments/run_frozen_analysis.py")
    result = runner.run(path, "blocked")
    assert result["status"] == "INPUT_BLOCKED" and not result["child_started"]
    assert ("INPUT_MISSING" if kind == "missing" else "SHA256_MISMATCH") in result["reason"]


def test_actual_package_manifest_and_archive_integrity():
    path, archive = os.environ.get("GNSS_E6_PACKAGE_ROOT"), os.environ.get("GNSS_E6_ZIP")
    if not path or not archive: pytest.skip("RC1 archive has not been created")
    root = Path(path)
    info = r.read_snapshot(root, root/"SOURCE_MANIFEST.json")
    assert info["head"] is None and len(info["files"]) > 20
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert not any(Path(n).suffix.lower() in (".dll", ".obs", ".rnx", ".bag") for n in z.namelist())


def test_relocated_import_with_original_source_access_blocked(tmp_path):
    path = os.environ.get("GNSS_E6_PACKAGE_ROOT")
    if not path: pytest.skip("RC1 has not been extracted")
    root = Path(path)
    forbidden = os.environ["GNSS_E6_FORBIDDEN_SOURCE"]
    script = tmp_path/"imports.py"
    script.write_text("import sys,importlib.util,json\nfrom pathlib import Path\n"
        f"root=Path({str(root)!r}); forbidden={forbidden!r}.replace('\\\\','/').lower()\n"
        "def block(event,args):\n"
        " if event=='open' and isinstance(args[0],str) and args[0].replace('\\\\','/').lower().startswith(forbidden):raise RuntimeError('original source access')\n"
        "sys.addaudithook(block)\n"
        "p=root/'tools/experiments/native_urbannav_obs.py'\ns=importlib.util.spec_from_file_location('isolated_native',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.parser_modules()\n"
        "files={n:v.__file__ for n,v in sys.modules.items() if n.startswith('gnss_toolbox') and getattr(v,'__file__',None)}\n"
        "assert files and all(Path(p).resolve().is_relative_to(root) for p in files.values())\nprint(json.dumps(files))\n")
    completed = subprocess.run([sys.executable,"-I","-B","-X","utf8",str(script)],cwd=root,capture_output=True,text=True,encoding="utf8",timeout=15)
    assert completed.returncode == 0, completed.stderr


def test_saved_real_relocated_window_and_full_regression():
    path = os.environ.get("GNSS_E6_REAL_RUN")
    if not path: pytest.skip("relocated window has not run yet")
    d = Path(path);meta = r.load_json(d/"run_metadata.json")
    summary = r.load_json(d/"replay/window_summary.json");comparison = r.load_json(d/"verification/e5_full_comparison.json")
    assert meta["status"] == "SUCCEEDED" and meta["code"]["identity_source"] == "SOURCE_SNAPSHOT"
    assert meta["code"]["head"] is None and summary["top_level_calls"] == 40
    assert summary["methods"]["A"]["accepted"] == 7 and summary["methods"]["B"]["accepted"] == 11
    assert comparison["status"] == "MATCHED" and comparison["runtime_outputs_unchanged"]
    assert max(comparison["numeric_max_abs_difference"].values()) == 0
    loaded = r.load_json(d/"replay/first_party_modules.json")
    assert loaded["all_within_code_root"] and all(Path(p).is_relative_to(Path(loaded["code_root"])) for p in loaded["modules"].values())
