"""
PackShield CLI entry point.

Current status:
- Two invocation paths, same underlying pipeline (run_pipeline):
    1. Explicit: `packshield install <pkg> --pm npm|pip`
    2. PATH-shim: real `npm install <pkg>` / `pip install <pkg>`, once
       `packshield shim install` has been run (see packshield/shim/setup.py).
       SCOPE LIMIT: only named-package installs are intercepted -- bare
       `npm install` / `pip install -r requirements.txt` pass through
       untouched (with a warning), and `python -m pip install <pkg>` can
       never be intercepted by any PATH shim (inherent limitation).
- Dependency resolution (dry-run, with hashes) IS implemented.
- S1, S3, S4 run together as Stage 1 (per Sec 6), combined via per-node
  MAX (no jointly-trained 3-feature model yet -- S3 has no paired
  training data; MAX is the honest interim, consistent with the
  MAX-not-average principle used throughout this pipeline).
- S4 live fetches use a last-known-good cache with fallback (see
  packshield/signals/s4_cache.py) -- fixes a real bug where transient
  API failures caused the same package to score differently run-to-run.
- S2 is a FAKE STUB (packshield/signals/s2_fake_stub.py) -- deterministic
  but meaningless, correctly gated behind Stage-1 >= 4/10 OR --shieldmax,
  per Sec 6.
- Tree-level MAX propagation across the full dependency tree IS real.
- Final verdict (BLOCK/WARN/ALLOW per Sec 6) IS real and ENFORCED: BLOCK
  stops the real install unless --override is given; WARN prompts the
  developer; ALLOW proceeds transparently. Every verdict is written to
  ~/.packshield/history.jsonl, including override records.
- Verdict cache (packshield/cache.py) is read but never written to yet.
- ShieldMax precedence (CLI flag > config.json > auto-escalation) IS
  implemented.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path as PathLib

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

from packshield.resolver import resolve_tree, ResolutionError
from packshield.cache import make_key, get_verdict
from packshield.signals.s1_name_similarity import score_name
from packshield.signals.s4_publisher_reputation import (
    _fetch_npm_features, _fetch_pip_features, _fetch_npm_downloads, _fetch_pip_downloads,
)
from packshield.signals.s4_cache import fetch_with_fallback, store_field, get_cached_field
from packshield.signals.s3_signature import extract_signature
from packshield.signals.s3_diff import diff_signatures
from packshield.signals.s3_fetch import fetch_npm_source, fetch_pip_source, FetchError
from packshield.signals.s3_store import get_previous_signature, store_signature
from packshield.signals.s2_fake_stub import run_fake_s2
from packshield.verdict.propagate import propagate_tree_scores
from packshield.verdict.verdict import compute_verdict
from packshield.config import get_shieldmax_default, get_config, set_shieldmax_default
from packshield.history import append_history
from packshield.shim.setup import install_shim, uninstall_shim, get_real_binary, install_profile_functions, uninstall_profile_functions
from packshield.live_status import start_scan, update_progress, finish_scan, log_event

console = Console()

MODEL_PATH = PathLib("data/stage1_model.joblib")
STAGE1_ESCALATION_THRESHOLD = 4.0  # provisional, per Sec 6 -- NOT final

_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    if not MODEL_PATH.exists():
        return None
    import joblib
    _model = joblib.load(MODEL_PATH)
    return _model


def _fetch_s4_features(name: str, ecosystem: str) -> dict:
    if ecosystem == "npm":
        features, _error = _fetch_npm_features(name)
        downloads, downloads_stale = fetch_with_fallback(
            ecosystem, name, "weekly_downloads", lambda: _fetch_npm_downloads(name)[0]
        )
    else:
        features, _error = _fetch_pip_features(name)
        downloads, downloads_stale = fetch_with_fallback(
            ecosystem, name, "weekly_downloads", lambda: _fetch_pip_downloads(name)[0]
        )

    result = features or {}
    core_fields = ("package_age_days", "days_since_last_publish", "total_versions",
                   "versions_last_90_days", "maintainer_count")
    if result:
        for field_name in core_fields:
            store_field(ecosystem, name, field_name, result.get(field_name))
    else:
        for field_name in core_fields:
            cached_val = get_cached_field(ecosystem, name, field_name)
            if cached_val is not None:
                result[field_name] = cached_val

    result["weekly_downloads"] = downloads
    result["_s4_used_stale_fallback"] = downloads_stale
    return result


def _compute_stage1_ml_score(model, s1_score: float, s4_features: dict) -> float | None:
    if model is None:
        return None
    row = pd.DataFrame([{
        "s1_score": s1_score,
        "package_age_days": s4_features.get("package_age_days"),
        "days_since_last_publish": s4_features.get("days_since_last_publish"),
        "total_versions": s4_features.get("total_versions"),
        "versions_last_90_days": s4_features.get("versions_last_90_days"),
        "maintainer_count": s4_features.get("maintainer_count"),
        "weekly_downloads": s4_features.get("weekly_downloads"),
    }])
    proba = model.predict_proba(row)[0][1]
    return round(proba * 10, 2)


def _run_s3(name: str, version: str, ecosystem: str):
    try:
        with tempfile.TemporaryDirectory(prefix="packshield-s3-") as tmp:
            tmp_path = PathLib(tmp)
            if ecosystem == "npm":
                source_dir = fetch_npm_source(name, version, tmp_path)
            else:
                source_dir = fetch_pip_source(name, version, tmp_path)
            new_sig = extract_signature(str(source_dir), ecosystem)
    except FetchError as e:
        return None, [f"S3 could not fetch/analyze source: {e}"]

    old_sig, skip_reason = get_previous_signature(ecosystem, name, version)
    if skip_reason:
        store_signature(ecosystem, name, version, new_sig)
        return 0.0, [skip_reason]

    result = diff_signatures(old_sig, new_sig)
    store_signature(ecosystem, name, version, new_sig)
    return result.score, result.reasons


def _colorize(score: float) -> str:
    if score >= 7:
        return f"[bold red]{score}[/bold red]"
    elif score >= 4:
        return f"[yellow]{score}[/yellow]"
    return f"{score}"

def _progress(message, stage="resolving", completed=None, total=None, current=None):
    """Observational only -- must never affect the real pipeline."""
    try:
        log_event(message, stage=stage, completed=completed, total=total, current=current)
    except Exception:
        pass

def run_pipeline(package: str, pm: str, shieldmax: bool, override_reason: str | None) -> int:
    """Core pipeline logic, callable from both `packshield install` and
    the PATH-shim interceptor. Returns the process exit code."""
    _scan_start_time = time.time()
    model = _load_model()
    console.print(
        "[bold yellow]⚠ Stage-1 (S1+S3+S4, per Sec 6) is real. S2 is a FAKE STUB "
        "(deterministic, meaningless) used only to test the gating/verdict/enforcement "
        "pipeline end-to-end. The final verdict below is REAL and WILL be enforced.[/bold yellow]"
    )
    shieldmax_active = shieldmax or get_shieldmax_default()
    if shieldmax_active:
        console.print("[dim](ShieldMax active -- S2 will run unconditionally on every package)[/dim]")

    console.print(f"[dim]Resolving full dependency tree for {package} ({pm}), dry-run only...[/dim]")

    try:
        start_scan(package, pm)
    except Exception:
        pass

    try:
        tree = resolve_tree(package, pm, progress=_progress)
    except ResolutionError as e:
        console.print(f"[bold red]✗ Dependency resolution failed: {e}[/bold red]")
        return 1

    table = Table(title=f"Resolved dependency tree — {len(tree)} package(s)")
    table.add_column("Package")
    table.add_column("Version")
    table.add_column("Cache")
    table.add_column("S1")
    table.add_column("Stage-1 (S1+S3+S4)")
    table.add_column("S3")
    table.add_column("Reasons")

    node_scores = []
    for entry in tree:
        _progress(f"scoring {entry['name']}@{entry['version']} ...", stage="stage1",
                  completed=len(node_scores), total=len(tree), current=entry["name"])
        key = make_key(pm, entry["name"], entry["version"], entry["hash"])
        cached = get_verdict(key)
        cache_status = "[green]HIT[/green]" if cached else "[yellow]MISS[/yellow]"

        s1 = score_name(entry["name"], pm)
        s4_features = _fetch_s4_features(entry["name"], pm)
        stage1_ml_score = _compute_stage1_ml_score(model, s1.score, s4_features)
        s3_score, s3_reasons = _run_s3(entry["name"], entry["version"], pm)

        s3_for_gating = s3_score if s3_score is not None else 0.0
        combined_stage1 = max(stage1_ml_score if stage1_ml_score is not None else 0.0, s3_for_gating)

        table.add_row(
            entry["name"], entry["version"], cache_status, f"{s1.score}",
            _colorize(combined_stage1), _colorize(s3_for_gating),
            "; ".join(s3_reasons) if s3_reasons else "-",
        )

        node_scores.append({
            "name": entry["name"],
            "version": entry["version"],
            "parent": entry.get("parent"),
            "s1_score": s1.score,
            "stage1_score": combined_stage1,
            "s3_score": s3_for_gating,
            "s2_fake_score": 0.0,
        })

    console.print(table)

    propagated = propagate_tree_scores(package, tree[-1]["version"] if tree else "unknown", node_scores)
    escalate = propagated.max_stage1 >= STAGE1_ESCALATION_THRESHOLD or shieldmax_active

    console.print()
    console.print(f"[bold]Stage-1 tree-max: {propagated.max_stage1}[/bold]  (escalate to S2? {'YES' if escalate else 'no'})")

    if escalate:
        console.print("[dim]Running S2 (fake stub) on every package in the tree...[/dim]")
        for i, entry in enumerate(tree):
            s2_result = run_fake_s2(entry["name"], entry["version"], pm)
            node_scores[i]["s2_fake_score"] = s2_result.score
            try:
                update_progress(entry["name"], len(node_scores), len(tree))
            except Exception:
                pass
        propagated = propagate_tree_scores(package, tree[-1]["version"] if tree else "unknown", node_scores)
        s2_for_verdict = propagated.max_s2_fake
    else:
        s2_for_verdict = None

    verdict = compute_verdict(propagated.max_stage1, s2_for_verdict)

    console.print()
    console.print(f"[bold]Final verdict for {package}: [/bold]", end="")
    if verdict.tier == "BLOCK":
        console.print(f"[bold red]BLOCK[/bold red] (final score {verdict.final_score}, worst offender: {propagated.worst_node} via {propagated.worst_signal})")
    elif verdict.tier == "WARN":
        console.print(f"[bold yellow]WARN[/bold yellow] (final score {verdict.final_score}, worst offender: {propagated.worst_node} via {propagated.worst_signal})")
    else:
        console.print(f"[green]ALLOW[/green] (final score {verdict.final_score})")

    history_entry = {
        "package": package,
        "pm": pm,
        "verdict": verdict.tier,
        "final_score": verdict.final_score,
        "stage1_score": verdict.stage1_score,
        "s2_score": verdict.s2_score,
        "s2_is_fake": True,
        "worst_node": propagated.worst_node,
        "worst_signal": propagated.worst_signal,
        "overridden": False,
        "override_reason": None,
        "node_scores": node_scores,  # NEW: full per-package tree breakdown, needed for the dashboard's dependency-tree view
    }

    proceed = False
    if verdict.tier == "ALLOW":
        proceed = True
    elif verdict.tier == "WARN":
        proceed = click.confirm(f"WARN verdict for {package} — proceed with install anyway?", default=False)
        if proceed:
            history_entry["overridden"] = True
    elif verdict.tier == "BLOCK":
        if override_reason:
            proceed = True
            history_entry["overridden"] = True
            history_entry["override_reason"] = override_reason
            console.print(f"[bold yellow]⚠ BLOCK overridden via --override: \"{override_reason}\"[/bold yellow]")
        else:
            console.print("[bold red]✗ Install BLOCKED. Use --override \"reason\" to force through anyway.[/bold red]")

    append_history(history_entry)

    try:
        finish_scan(verdict.tier, verdict.final_score, _scan_start_time)
    except Exception:
        pass

    if not proceed:
        return 1

    real_binary = shutil.which(pm)
    if real_binary is None:
        console.print(f"[bold red]✗ Could not find a real `{pm}` binary on PATH.[/bold red]")
        return 1

    console.print(f"[dim]→ passing through to real {pm}: {real_binary} install {package}[/dim]")
    
    
    result = subprocess.run([real_binary, "install", package])
    return result.returncode


@click.group()
@click.version_option()
def main():
    """PackShield — Developer Package Shield."""
    pass


@main.command()
@click.argument("package")
@click.option("--pm", type=click.Choice(["npm", "pip"]), required=True, help="Package manager to use for this install.")
@click.option("--shieldmax", is_flag=True, default=False, help="Force S2 to run regardless of Stage-1 score.")
@click.option("--override", "override_reason", default=None, help="Force a BLOCK verdict through anyway, with a reason.")
def install(package: str, pm: str, shieldmax: bool, override_reason: str | None):
    """Install PACKAGE via the given package manager (--pm npm|pip)."""
    sys.exit(run_pipeline(package, pm, shieldmax, override_reason))


@main.group()
def config():
    """View or change persistent PackShield settings (~/.packshield/config.json)."""
    pass


@config.command("show")
def config_show():
    """Show current config values."""
    from packshield.config import CONFIG_PATH
    current = get_config()
    console.print(f"[bold]Config file:[/bold] {CONFIG_PATH if CONFIG_PATH.exists() else str(CONFIG_PATH) + ' (not yet created, showing defaults)'}")
    for key, value in current.items():
        console.print(f"  {key}: {value}")


@config.command("set-shieldmax")
@click.argument("state", type=click.Choice(["on", "off"]))
def config_set_shieldmax(state: str):
    """Set the persistent ShieldMax default (equivalent to the dashboard's
    'Paranoid Mode' toggle, which doesn't exist yet). Precedence per Sec 6:
    the one-off --shieldmax CLI flag always overrides this."""
    set_shieldmax_default(state == "on")
    console.print(f"[green]shieldmax_default set to {state == 'on'}. This affects every future install "
                  f"unless overridden by --shieldmax on that specific call.[/green]")


@main.group()
def shim():
    """Manage PATH-shim interception of real npm/pip commands.

    SCOPE LIMIT: only intercepts `npm install <pkg>` / `pip install <pkg>`
    with an explicit package name. Bare installs and `python -m pip`
    are not covered -- see packshield/shim/setup.py docstring."""
    pass


from packshield.shim.setup import install_shim, uninstall_shim, get_real_binary, install_profile_functions, uninstall_profile_functions


@shim.command("install")
def shim_install():
    """Install PATH-shim files AND PowerShell profile functions (the
    profile functions are what actually make interception reliable on
    Windows -- see packshield/shim/setup.py docstring for why)."""
    ok1, msg1 = install_shim()
    ok2, msg2 = install_profile_functions()
    console.print(f"[green]{msg1}[/green]" if ok1 else f"[bold red]{msg1}[/bold red]")
    console.print(f"[green]{msg2}[/green]" if ok2 else f"[bold red]{msg2}[/bold red]")


@shim.command("uninstall")
def shim_uninstall():
    ok1, msg1 = uninstall_shim()
    ok2, msg2 = uninstall_profile_functions()
    console.print(f"[green]{msg1}[/green]" if ok1 else f"[bold red]{msg1}[/bold red]")
    console.print(f"[green]{msg2}[/green]" if ok2 else f"[bold red]{msg2}[/bold red]")


@main.command()
@click.option("--port", default=8000, help="Port to run the local dashboard on.")
@click.option("--no-browser", is_flag=True, default=False, help="Don't auto-open a browser tab.")
def ui(port: int, no_browser: bool):
    """Launch the local, read-only PackShield dashboard.

    This dashboard NEVER gates, delays, or influences any install --
    the CLI/PATH-shim enforces entirely on its own, with or without
    this ever being opened. See packshield/dashboard/server.py.
    """
    import uvicorn
    import webbrowser
    import threading

    url = f"http://127.0.0.1:{port}"
    console.print(f"[bold green]PackShield Dashboard (read-only) running at {url}[/bold green]")
    console.print("[dim]This dashboard cannot affect any install. Ctrl+C to stop.[/dim]")

    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run("packshield.dashboard.server:app", host="127.0.0.1", port=port, log_level="warning")


@main.command(
    name="_shim_intercept",
    hidden=True,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("pm")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def shim_intercept(pm: str, args: tuple):
    """Hidden command: called by the npm.cmd/pip.cmd shim scripts. Not
    intended to be invoked directly by a person."""
    real_binary = get_real_binary(pm)
    if not real_binary:
        console.print(f"[bold red]✗ Shim misconfigured: no real {pm} path recorded. Run `packshield shim install` again.[/bold red]")
        sys.exit(1)

    args = list(args)
    is_install = len(args) >= 1 and args[0] in ("install", "i", "add")
    has_named_package = len(args) >= 2 and not args[1].startswith("-")

    if not is_install or not has_named_package:
        if is_install and not has_named_package:
            console.print(
                "[bold yellow]⚠ PackShield: bare install (no named package) is not yet "
                "covered by this pipeline -- passing through WITHOUT scoring.[/bold yellow]"
            )
        result = subprocess.run([real_binary] + args)
        sys.exit(result.returncode)

    package = args[1]
    sys.exit(run_pipeline(package, pm, shieldmax=False, override_reason=None))


if __name__ == "__main__":
    main()