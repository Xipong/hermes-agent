"""Offline consumers for #134640/#146236: no provider calls or quality claims."""
import json
from pathlib import Path

import pytest
import yaml

from evals.toolperf_abeval import ab_eval, guidance_cases, measurement
from evals.toolperf_abeval.offline_smoke import exercise


@pytest.mark.parametrize("task", [*guidance_cases.TASKS, "guidance_trivial_edit"])
def test_actual_fixture_actions_reach_trace_scorer(tmp_path, task):
    pytest.importorskip("nemo_relay")
    result = exercise(tmp_path / "run", task)
    assert result["ok"]
    assert not any(value for key, value in result.items() if key != "ok")


@pytest.mark.parametrize("task", ["accept_bug_fix", "accept_shared_schema", "accept_changed_after_pass",
                                  "accept_required_workflow", "accept_async_write", "accept_learning_update",
                                  "guidance_arithmetic"])
def test_omitted_required_evidence_cannot_pass(tmp_path, task):
    pytest.importorskip("nemo_relay")
    assert not exercise(tmp_path / "run", task, omit_gate=True)["ok"]


@pytest.mark.parametrize("task,metric", [
    ("accept_bug_fix", "unnecessary_checks"),
    ("accept_committed_write", "unnecessary_readbacks"),
    ("guidance_trivial_edit", "unnecessary_readbacks"),
    ("accept_learning_noop", "skill_edits_without_lesson"),
])
def test_extra_work_measured_separately_from_correctness(tmp_path, task, metric):
    pytest.importorskip("nemo_relay")
    result = exercise(tmp_path / "run", task, extra=True)
    assert result["ok"]
    assert result[metric] == 1


def test_report_rejects_correct_disk_without_trivial_edit_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(ab_eval, "ROOT", tmp_path)
    results = tmp_path / "results/model/all_on"
    results.mkdir(parents=True)
    project = tmp_path / "runs/model/all_on/guidance_trivial_edit-r0/proj"
    project.mkdir(parents=True)
    (project / "flag.txt").write_text("enabled")
    (results / "meta.jsonl").write_text(json.dumps({"run_id": "guidance_trivial_edit-r0",
        "task": "guidance_trivial_edit", "exit": 0, "wall_s": 1, "tail": "DONE"}) + "\n")
    ab_eval.report(["model"], ["all_on"])
    result = json.loads((results.parent / "report.json").read_text())
    assert result["summary"]["all_on"]["accepted"] == 0
    assert result["summary"]["all_on"]["cost_per_success_usd"] is None
    assert not result["paired"]


def test_arms_change_one_block_and_preserve_skill_workflow(tmp_path, monkeypatch):
    home = tmp_path / "source"
    home.mkdir()
    (home / "config.yaml").write_text("agent:\n  reasoning_effort: high\nmodel: fixed-model\n")
    skill = home / "skills/required/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Required workflow\nRun affected check.\n")
    monkeypatch.setattr(ab_eval, "HOME", home)
    baseline = ab_eval.GUIDANCE_ARMS["all_on"]
    for arm, switches in ab_eval.GUIDANCE_ARMS.items():
        target = ab_eval._home_for_guidance_arm(tmp_path / arm, arm)
        config = yaml.safe_load((target / "config.yaml").read_text())
        changed = [key for key in baseline if switches[key] != baseline[key]]
        if arm not in {"all_on", "all_off"}:
            assert len(changed) == 1
        if arm == "all_off":
            assert all(not value for value in switches.values())
        assert config["agent"] == {"reasoning_effort": "high", **switches}
        assert (target / "skills/required/SKILL.md").read_bytes() == skill.read_bytes()


def test_pairing_rejects_effort_skills_and_task_drift(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    config = home / "config.yaml"
    config.write_text("agent:\n  reasoning_effort: high\n")
    source = str(Path(__file__).parents[2])
    tasks = {"probe": "do the task"}
    receipt = measurement.pairing_receipt(home, "fixed-model", source, tasks)
    target = tmp_path / "pairing.json"
    measurement.freeze_receipt(target, receipt)
    measurement.freeze_receipt(target, measurement.pairing_receipt(home, "fixed-model", source, tasks))
    config.write_text("agent:\n  reasoning_effort: low\n")
    with pytest.raises(ValueError, match="paired inputs changed"):
        measurement.freeze_receipt(target, measurement.pairing_receipt(home, "fixed-model", source, tasks))
    config.write_text("agent:\n  reasoning_effort: high\n")
    (home / "SKILL.md").write_text("new workflow")
    with pytest.raises(ValueError, match="paired inputs changed"):
        measurement.freeze_receipt(target, measurement.pairing_receipt(home, "fixed-model", source, tasks))
    (home / "SKILL.md").unlink()
    with pytest.raises(ValueError, match="paired inputs changed"):
        measurement.freeze_receipt(target, measurement.pairing_receipt(home, "fixed-model", source, {"probe": "different"}))


def test_runner_retains_failed_attempt_and_refuses_arm_reuse(tmp_path, monkeypatch):
    """Run the real orchestrator with a local failing child, never a provider."""
    import subprocess
    import sys
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("agent:\n  reasoning_effort: high\n")
    monkeypatch.setattr(ab_eval, "ROOT", tmp_path / "output")
    monkeypatch.setattr(ab_eval, "HOME", home)
    original = subprocess.run
    launches = []

    def local_child(argv, **kwargs):
        if "hermes_cli.main" not in argv:
            return original(argv, **kwargs)
        launches.append(argv)
        config = yaml.safe_load((Path(kwargs["env"]["HERMES_HOME"]) / "config.yaml").read_text())
        assert config["agent"]["execution_guidance"] is False
        assert config["agent"]["reasoning_effort"] == "high"
        return original([sys.executable, "-c", "raise SystemExit(7)"], **kwargs)

    monkeypatch.setattr(subprocess, "run", local_child)
    source = str(Path(__file__).parents[2])
    ab_eval.run("candidate", "fixed-model", 1, source, ["guidance_trivial_edit"], "execution_off")
    meta = ab_eval.ROOT / "results/fixed-model/candidate/meta.jsonl"
    assert json.loads(meta.read_text())["exit"] == 7
    ab_eval.report(["fixed-model"], ["candidate"])
    result = json.loads((meta.parent.parent / "report.json").read_text())
    assert result["summary"]["candidate"]["attempts"] == 1
    assert result["summary"]["candidate"]["accepted"] == 0
    with pytest.raises(ValueError, match="paired inputs changed"):
        ab_eval.run("candidate", "fixed-model", 1, source, ["guidance_trivial_edit"], "all_on")
    assert len(launches) == 1


def test_usage_is_nullable_and_does_not_double_count_reasoning(tmp_path):
    trace = tmp_path / "usage.jsonl"
    event = {"kind": "scope", "category": "llm", "scope_category": "end", "data": {"usage": {
        "prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 60},
        "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 8}, "cost": 0.02}}}
    trace.write_text(json.dumps(event) + "\n")
    usage = measurement.usage_metrics(trace)
    assert usage == {"input_tokens": 100, "cached_input_tokens": 60, "uncached_input_tokens": 40,
                     "output_tokens": 20, "reasoning_tokens": 8, "total_tokens": 120, "cost_usd": 0.02}
    summary = measurement.totals([{**usage, "ok": True}, {**usage, "ok": False}])
    assert summary["cost_per_success_usd"] == pytest.approx(0.04)
    trace.write_text(json.dumps(event) + "\n" + json.dumps({**event, "data": {}}) + "\n")
    assert all(value is None for value in measurement.usage_metrics(trace).values())
    assert measurement.totals([{**usage, "ok": False}])["cost_per_success_usd"] is None


def test_anthropic_cache_categories_and_missing_billing_are_not_guessed(tmp_path):
    trace = tmp_path / "usage.jsonl"
    trace.write_text(json.dumps({"kind": "scope", "category": "llm", "scope_category": "end",
        "data": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 50,
                           "cache_creation_input_tokens": 5, "output_tokens": 7}},
        "annotated_response": {"cost": 99}}) + "\n")
    result = measurement.usage_metrics(trace)
    assert result["input_tokens"] == 65
    assert result["uncached_input_tokens"] == 15
    assert result["total_tokens"] == 72
    assert result["cost_usd"] is None
    assert result["reasoning_tokens"] is None
