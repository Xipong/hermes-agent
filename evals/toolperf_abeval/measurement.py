"""Pairing receipts and provider-reported usage for guidance experiments."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from evals.toolperf_abeval.guidance_cases import events, payload


METRICS = ("input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens",
           "reasoning_tokens", "total_tokens", "cost_usd")


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def usage_metrics(trace):
    """Read raw provider usage, never Relay's price-estimated annotations.

    Unknown or partially observed metrics remain null, not a misleading zero.
    Anthropic input excludes cache reads/writes; OpenAI input includes cached tokens.
    Reasoning is a subset of output: never add it again to total.
    """
    rows = []
    for event in events(trace):
        if (event.get("kind"), event.get("category"), event.get("scope_category")) != ("scope", "llm", "end"):
            continue
        data = payload(event.get("data"))
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        row: dict[str, int | float | None] = dict.fromkeys(METRICS)
        output = _number(usage.get("completion_tokens", usage.get("output_tokens")))
        raw_input = _number(usage.get("prompt_tokens", usage.get("input_tokens")))
        if "cache_read_input_tokens" in usage:
            cached = _number(usage.get("cache_read_input_tokens"))
            creation = _number(usage.get("cache_creation_input_tokens"))
            uncached = raw_input + creation if raw_input is not None and creation is not None else None
            total_input = uncached + cached if uncached is not None and cached is not None else None
        else:
            details = usage.get("prompt_tokens_details", usage.get("input_tokens_details")) or {}
            cached = _number(details.get("cached_tokens"))
            total_input = raw_input
            uncached = raw_input - cached if raw_input is not None and cached is not None and cached <= raw_input else None
        details = usage.get("completion_tokens_details", usage.get("output_tokens_details")) or {}
        total = _number(usage.get("total_tokens"))
        if total is None and total_input is not None and output is not None:
            total = total_input + output
        row.update(input_tokens=total_input, cached_input_tokens=cached, uncached_input_tokens=uncached,
                   output_tokens=output, reasoning_tokens=_number(details.get("reasoning_tokens")),
                   total_tokens=total, cost_usd=_number(usage.get("cost")))
        rows.append(row)
    return {key: sum(row[key] for row in rows) if rows and all(row[key] is not None for row in rows) else None
            for key in METRICS}


def pairing_receipt(home, model, pythonpath, tasks, output_root=None):
    """Freeze actual config/skills/tools and source, not just the arm label."""
    source = Path(pythonpath).resolve()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True, timeout=30).strip()
    files = {}
    for path in sorted(home.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(home))] = hashlib.sha256(path.read_bytes()).hexdigest()
    config_path = home / "config.yaml"
    import hermes_yaml as yaml
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    reasoning = (config or {}).get("agent", {}).get("reasoning_effort")
    from hermes_constants import parse_reasoning_effort
    if not isinstance(reasoning, str) or parse_reasoning_effort(reasoning) is None:
        raise ValueError("pin a valid agent.reasoning_effort in the dedicated eval config")
    environment = {key: hashlib.sha256(value.encode()).hexdigest()
                   for key, value in os.environ.items()
                   if key.startswith(("HERMES_", "OPENAI_", "ANTHROPIC_", "TERMINAL_"))}
    untracked = {}
    for name in git("ls-files", "--others", "--exclude-standard").splitlines():
        path = source / name
        if path.is_file() and not (output_root and path.is_relative_to(output_root)):
            untracked[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"untracked_sha256": untracked, "model": model, "reasoning_effort_config": reasoning,
               "home_sha256": files, "environment_sha256": environment, "tasks": tasks, "source_commit": git("rev-parse", "HEAD"),
               "source_diff_sha256": hashlib.sha256(git("diff", "HEAD", "--").encode()).hexdigest()}
    receipt["pair_id"] = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    return receipt


def freeze_receipt(path, receipt):
    if path.exists():
        if json.loads(path.read_text()) != receipt:
            raise ValueError(f"paired inputs changed: {path}; use a fresh result root")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def totals(rows):
    accepted = sum(bool(row["ok"]) for row in rows)
    metrics = {key: sum(row[key] for row in rows)
               if rows and all(row.get(key) is not None for row in rows) else None for key in METRICS}
    cost = metrics["cost_usd"]
    return {"attempts": len(rows), "accepted": accepted, **metrics,
            "cost_per_success_usd": cost / accepted if cost is not None and accepted else None}
