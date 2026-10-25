"""E1 process/identity tests use temporary inputs, never navigation solvers."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/experiments/run_frozen_analysis.py"
spec = importlib.util.spec_from_file_location("e1_frozen_analysis", ENTRY)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf8")


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "source"
    e0 = tmp_path / "e0"
    data = tmp_path / "data"
    for p in [source, e0, data]:
        p.mkdir()
    (e0 / "FREEZE_README_E0.md").write_text("TEST_E0_ID", encoding="utf8")
    (e0 / "FILE_MANIFEST_E0.csv").write_text("path,sha256\n", encoding="utf8")
    dump(source / "input.json", {"n": 42})
    dump(source / "expected.json", {"n": 42})
    script = source / "analysis.py"
    script.write_text("import argparse,json,sys\nfrom pathlib import Path\n"
                      "p=argparse.ArgumentParser();p.add_argument('--out');o=Path(p.parse_args().out)\n"
                      "value=json.loads((o/'input.json').read_text())\n"
                      "(o/'result.json').write_text(json.dumps(value))\n"
                      "print('analysis completed')\n", encoding="utf8")
    config = {"version": 1, "experiment_id": "E1_TEMPORARY_TEST", "python": sys.executable,
              "source_results": str(source), "e0": {"freeze_id": "TEST_E0_ID", "directory": str(e0),
              "readme_sha256": sha(e0 / "FREEZE_README_E0.md"), "file_manifest_sha256": sha(e0 / "FILE_MANIFEST_E0.csv")},
              "output_root": str(tmp_path / "runs"), "protected_roots": [str(data)], "timeout_seconds": 5,
              "dependencies": [], "analysis": {"script": "analysis.py", "sha256": sha(script),
              "directory": "gnss_return08", "arguments": ["--out", "{analysis_dir}"]},
              "inputs": [{"source": "input.json", "destination": "gnss_return08/input.json", "sha256": sha(source / "input.json"), "role": "test_saved_input"}],
              "comparisons": [{"expected": "expected.json", "actual": "gnss_return08/result.json", "kind": "json_exact", "sha256": sha(source / "expected.json")}]}
    path = tmp_path / "config.json"
    dump(path, config)
    return path, config, source, script


def test_valid_configuration_executes_and_records_exact_result(setup):
    path, config, source, script = setup
    before = {p.name: sha(p) for p in source.iterdir()}
    result = runner.run(path, "success")
    assert result["status"] == "SUCCEEDED" and result["exit_code"] == 0
    assert result["original_inputs_unchanged"] and result["copied_inputs_unchanged"]
    assert result["wrapper"]["sha256"] == sha(ENTRY)
    assert result["analysis_script"]["sha256"] == sha(script)
    assert result["configuration"]["sha256"] == sha(path)
    assert result["python"]["path"] and result["code"]["head"]
    assert result["command"][1:5] == ["-I", "-B", "-X", "utf8"]
    out = Path(result["output_directory"])
    assert json.loads((out / "result_comparison.json").read_text())["all_equal"]
    assert "analysis completed" in (out / "stdout.log").read_text()
    assert result == json.loads((out / "run_metadata.json").read_text(encoding="utf8"))
    assert before == {p.name: sha(p) for p in source.iterdir()}


@pytest.mark.parametrize("problem", ["missing", "digest"])
def test_bad_input_is_rejected_before_analysis(setup, problem):
    path, config, source, script = setup
    if problem == "missing":
        (source / "input.json").unlink()
    else:
        (source / "input.json").write_text("tampered", encoding="utf8")
    result = runner.run(path, problem)
    assert result["status"] == "INPUT_BLOCKED" and not result["child_started"]
    assert ("INPUT_MISSING" if problem == "missing" else "SHA256_MISMATCH") in result["reason"]
    out = Path(result["output_directory"])
    assert not (out / "work").exists()
    assert (out / "run_metadata.json").is_file() and (out / "stderr.log").stat().st_size


def test_existing_run_is_not_changed_and_rejection_has_own_record(setup):
    path, config, source, script = setup
    first = runner.run(path, "once")
    old = Path(first["output_directory"])
    before = {str(p.relative_to(old)): sha(p) for p in old.rglob("*") if p.is_file()}
    second = runner.run(path, "once")
    assert second["status"] == "INPUT_BLOCKED" and not second["child_started"]
    assert "RUN_ID_EXISTS" in second["reason"]
    assert "_rejections" in second["output_directory"]
    assert before == {str(p.relative_to(old)): sha(p) for p in old.rglob("*") if p.is_file()}


@pytest.mark.parametrize("where", ["e0", "source_results", "raw"])
def test_output_path_protection_before_writing(setup, where):
    path, config, source, script = setup
    target = {"e0": config["e0"]["directory"], "source_results": config["source_results"], "raw": config["protected_roots"][0]}[where]
    config["output_root"] = str(Path(target) / "nested")
    dump(path, config)
    result = runner.run(path, "blocked")
    assert result["status"] == "INPUT_BLOCKED" and result["reason"] == "OUTPUT_PATH_PROTECTED"
    assert not Path(config["output_root"]).exists()


@pytest.mark.parametrize("run_id", ["../escape", "bad/child", "CON", "bad."])
def test_run_id_cannot_escape_or_alias_a_windows_device(setup, run_id):
    path, config, source, script = setup
    result = runner.run(path, run_id)
    assert result["status"] == "INPUT_BLOCKED" and result["reason"] == "INVALID_RUN_ID"
    assert not Path(config["output_root"]).exists()


def test_dry_run_creates_no_output_and_executes_no_analysis(setup):
    path, config, source, script = setup
    result = runner.run(path, "dry", dry_run=True)
    assert result["status"] == "DRY_RUN_READY" and not result["child_started"]
    assert not Path(config["output_root"]).exists()


@pytest.mark.parametrize("mode", ["failure", "timeout"])
def test_subprocess_errors_keep_logs_and_exact_state(setup, mode):
    path, config, source, script = setup
    script.write_text("import sys,time\nprint('child started',flush=True)\nprint('child stderr',file=sys.stderr,flush=True)\n" +
                      ("raise SystemExit(7)\n" if mode == "failure" else "time.sleep(20)\n"), encoding="utf8")
    config["analysis"]["sha256"] = sha(script)
    config["timeout_seconds"] = 0.25 if mode == "timeout" else 5
    dump(path, config)
    result = runner.run(path, mode)
    assert result["status"] == ("FAILED" if mode == "failure" else "TIMED_OUT")
    assert result["child_started"] and result["original_inputs_unchanged"]
    assert result["exit_code"] == 7 if mode == "failure" else result["exit_code"] != 0
    out = Path(result["output_directory"])
    assert (out / "stdout.log").exists() and (out / "stderr.log").stat().st_size
    assert result["wrapper_exit_code"] == (1 if mode == "failure" else 124)
    assert result["elapsed_seconds"] < 10


def test_scientific_difference_is_preserved_without_tolerance_change(setup):
    path, config, source, script = setup
    dump(source / "expected.json", {"n": 43})
    config["comparisons"][0]["sha256"] = sha(source / "expected.json")
    dump(path, config)
    result = runner.run(path, "difference")
    assert result["status"] == "FAILED" and result["reason"] == "SCIENTIFIC_RESULT_MISMATCH"
    comparison = json.loads((Path(result["output_directory"]) / "result_comparison.json").read_text())
    assert comparison["files"][0]["actual_values"] == {"n": 42}
    assert comparison["files"][0]["reference_values"] == {"n": 43}


def test_explicit_input_boundary_remains_active_under_optimization(setup):
    path, config, source, script = setup
    config["inputs"][0]["sha256"] = "0" * 64
    dump(path, config)
    result = subprocess.run([sys.executable, "-O", "-B", "-X", "utf8", str(ENTRY), "--config", str(path), "--run-id", "optimized"],
                            capture_output=True, text=True, encoding="utf8", timeout=15)
    assert result.returncode == 2
    metadata = json.loads(result.stderr)
    assert metadata["status"] == "INPUT_BLOCKED" and not metadata["child_started"]


def test_post_execution_source_change_is_reported_without_restoration(setup):
    path, config, source, script = setup
    script.write_text("from pathlib import Path\nPath(" + repr(str(source / "input.json")) + ").write_text('changed during test')\n", encoding="utf8")
    config["analysis"]["sha256"] = sha(script)
    dump(path, config)
    result = runner.run(path, "changed")
    assert result["status"] == "FAILED" and result["reason"] == "ORIGINAL_INPUT_CHANGED"
    assert not result["original_inputs_unchanged"]
