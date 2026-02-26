"""Command-line interface for multi-model code review."""

import asyncio
import sys

import click

import json

from . import Verdict
from .aggregator import aggregate_reviews
from .git_utils import get_diff, read_file_content
from .lint import get_changed_python_files, run_lint_checks, run_lint_fixes
from .observations import run_observations
from .prompts import build_observe_prompt, build_review_prompt, build_spec_check_prompt
from .report import format_aggregate_review, format_summary
from .reviewer import (
    observe_with_model,
    parse_observe_response,
    preflight_check,
    review_with_model,
    review_with_models,
    run_model,
)

DEFAULT_MODELS = ["claude", "gemini"]


@click.group()
@click.version_option()
def cli():
    """Multi-model code review - AI-first review using multiple models."""
    pass


@cli.command()
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--spec",
    "-s",
    default=None,
    help="Path to spec file for compliance checking",
)
@click.option(
    "--model",
    "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["full", "summary"]),
    default="full",
    help="Output format (default: full)",
)
@click.option(
    "--output-dir",
    "-d",
    type=click.Path(),
    default=None,
    help="Directory to save outputs (report.md + per-model raw responses)",
)
@click.option(
    "--lint/--no-lint",
    default=False,
    help="Run lint checks (black, isort, ruff) before model review",
)
@click.option(
    "--fix-lint",
    is_flag=True,
    default=False,
    help="Auto-fix lint issues before model review",
)
@click.option(
    "--observations",
    type=click.Path(exists=True),
    default=None,
    help="JSON file with observation results (from 'observe' command)",
)
def review(branch, base, repo, spec, model, output, output_dir, lint, fix_lint, observations):
    """Run code review with multiple models."""
    models = list(model) if model else DEFAULT_MODELS

    # Lint fix/check (pre-model gate)
    if fix_lint or lint:
        py_files = get_changed_python_files(branch, base, cwd=repo)
        if py_files:
            if fix_lint:
                click.echo(f"Fixing lint issues on {len(py_files)} files...", err=True)
                fix_result = run_lint_fixes(py_files, cwd=repo)
                if fix_result.total_fixed > 0:
                    click.echo(fix_result.summary, err=True)

            click.echo(f"Running lint checks on {len(py_files)} files...", err=True)
            lint_result = run_lint_checks(py_files, cwd=repo)
            if not lint_result.passed:
                click.echo("Lint checks failed:", err=True)
                click.echo(lint_result.summary, err=True)
                sys.exit(2)
            click.echo("Lint checks passed", err=True)

    # Preflight check
    missing = preflight_check(models)
    if missing:
        click.echo(f"Error: Missing CLI tools: {', '.join(missing)}", err=True)
        click.echo("Install the missing tools or use --model to select available ones.", err=True)
        sys.exit(1)

    # Get diff
    try:
        if branch:
            diff_ref = branch
            diff_content = get_diff(branch, base, cwd=repo)
        else:
            diff_ref = "staged"
            diff_content = get_diff(cwd=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not diff_content.strip():
        click.echo("No changes to review.", err=True)
        sys.exit(0)

    # Read spec if provided
    spec_content = None
    if spec:
        spec_content = read_file_content(spec)
        if spec_content is None:
            click.echo(f"Warning: Spec file not found: {spec}", err=True)

    # Load observations if provided
    obs_data = None
    if observations:
        with open(observations) as f:
            obs_data = json.load(f)
        click.echo(f"Loaded {len(obs_data)} observation(s) from {observations}", err=True)

    # Build prompt
    prompt = build_review_prompt(diff_content, spec_content, observations=obs_data)

    # Run reviews
    click.echo(f"Running review with {', '.join(models)}...", err=True)
    reviews = asyncio.run(review_with_models(models, prompt, observations=obs_data))

    # Aggregate
    result = aggregate_reviews(diff_ref, reviews, spec)

    # Format output
    if output == "full":
        report = format_aggregate_review(result)
    else:
        report = format_summary(result)

    # Save to files if output-dir specified
    if output_dir:
        import os

        os.makedirs(output_dir, exist_ok=True)

        # Save report
        report_path = os.path.join(output_dir, "report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        click.echo(f"Saved report to {report_path}", err=True)

        # Save raw responses per model
        for model_review in reviews:
            raw_path = os.path.join(output_dir, f"{model_review.model}-raw.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(model_review.raw_response)
            click.echo(f"Saved {model_review.model} raw response to {raw_path}", err=True)

    # Always output to stdout
    click.echo(report)


@cli.command()
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to analyze (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--model",
    "-m",
    default="claude",
    help="Model to use for observation gathering (default: claude)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output file for observations JSON (default: stdout)",
)
@click.option(
    "--run/--no-run",
    default=True,
    help="Run observations after gathering (default: --run)",
)
def observe(branch, base, repo, model, output, run):
    """
    Gather observations needed for code review.

    Analyzes the diff and determines what additional information is needed,
    then optionally runs the observations. Output can be passed to 'review --observations'.

    Example workflow:
        code-review observe -b feature-branch -o obs.json
        code-review review -b feature-branch --observations obs.json
    """
    # Get diff
    try:
        if branch:
            diff_ref = branch
            diff_content = get_diff(branch, base, cwd=repo)
        else:
            diff_ref = "staged"
            diff_content = get_diff(cwd=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not diff_content.strip():
        click.echo("No changes to analyze.", err=True)
        sys.exit(0)

    # Preflight check
    if not preflight_check([model]) == []:
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    # Run observation gathering
    click.echo(f"Gathering observations with {model}...", err=True)
    requested_obs = asyncio.run(observe_with_model(model, diff_content))

    if not requested_obs:
        click.echo("No observations needed.", err=True)
        result = {}
    else:
        click.echo(f"Model requested {len(requested_obs)} observation(s):", err=True)
        for obs in requested_obs:
            click.echo(f"  - {obs.get('tool')}: {obs.get('name')}", err=True)

        if run:
            # Run the observations
            click.echo("Running observations...", err=True)
            result = asyncio.run(run_observations(requested_obs, repo))
            click.echo(f"Completed {len(result)} observation(s)", err=True)
        else:
            # Just output the requests (--no-run)
            result = {"_requests": requested_obs, "_results": {}}

    # Output
    output_json = json.dumps(result, indent=2, default=str)
    if output:
        with open(output, "w") as f:
            f.write(output_json)
        click.echo(f"Saved observations to {output}", err=True)
    else:
        click.echo(output_json)


@cli.command()
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--spec",
    "-s",
    default=None,
    help="Path to spec file for compliance checking",
)
@click.option(
    "--model",
    "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
@click.option(
    "--output-dir",
    "-d",
    type=click.Path(),
    default=None,
    help="Directory to save outputs (report.md + per-model raw responses)",
)
@click.option(
    "--lint/--no-lint",
    default=False,
    help="Run lint checks (black, isort, ruff) before model review",
)
@click.option(
    "--fix-lint",
    is_flag=True,
    default=False,
    help="Auto-fix lint issues before model review",
)
def gate(branch, base, repo, spec, model, output_dir, lint, fix_lint):
    """
    Run review and exit with code based on result.

    Exit codes:
    - 0: PASS (all models pass)
    - 1: CONCERN (at least one concern, no blocks)
    - 2: BLOCK (at least one model blocks)
    """
    models = list(model) if model else DEFAULT_MODELS

    # Lint fix/check (pre-model gate)
    if fix_lint or lint:
        py_files = get_changed_python_files(branch, base, cwd=repo)
        if py_files:
            if fix_lint:
                click.echo(f"Fixing lint issues on {len(py_files)} files...", err=True)
                fix_result = run_lint_fixes(py_files, cwd=repo)
                if fix_result.total_fixed > 0:
                    click.echo(fix_result.summary, err=True)

            click.echo(f"Running lint checks on {len(py_files)} files...", err=True)
            lint_result = run_lint_checks(py_files, cwd=repo)
            if not lint_result.passed:
                click.echo("Lint checks failed:", err=True)
                click.echo(lint_result.summary, err=True)
                sys.exit(2)  # Block on lint failure
            click.echo("Lint checks passed", err=True)

    # Preflight check
    missing = preflight_check(models)
    if missing:
        click.echo(f"Error: Missing CLI tools: {', '.join(missing)}", err=True)
        sys.exit(2)  # Block on missing tools

    # Get diff
    try:
        if branch:
            diff_ref = branch
            diff_content = get_diff(branch, base, cwd=repo)
        else:
            diff_ref = "staged"
            diff_content = get_diff(cwd=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    if not diff_content.strip():
        click.echo("No changes to review.")
        sys.exit(0)

    # Read spec if provided
    spec_content = None
    if spec:
        spec_content = read_file_content(spec)

    # Build prompt
    prompt = build_review_prompt(diff_content, spec_content)

    # Run reviews
    click.echo(f"Running gate check with {', '.join(models)}...", err=True)
    reviews = asyncio.run(review_with_models(models, prompt))

    # Aggregate
    result = aggregate_reviews(diff_ref, reviews, spec)

    # Save to files if output-dir specified
    if output_dir:
        import os

        os.makedirs(output_dir, exist_ok=True)

        # Save full report
        report_path = os.path.join(output_dir, "report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(format_aggregate_review(result))
        click.echo(f"Saved report to {report_path}", err=True)

        # Save raw responses per model
        for model_review in reviews:
            raw_path = os.path.join(output_dir, f"{model_review.model}-raw.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(model_review.raw_response)
            click.echo(f"Saved {model_review.model} raw response to {raw_path}", err=True)

    # Output summary
    click.echo(format_summary(result))

    # Exit with appropriate code
    if result.gate == Verdict.PASS:
        sys.exit(0)
    elif result.gate == Verdict.CONCERN:
        sys.exit(1)
    else:
        sys.exit(2)


@cli.command()
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--model",
    "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
def compare(branch, base, repo, model):
    """Show only disagreements between models."""
    models = list(model) if model else DEFAULT_MODELS

    if len(models) < 2:
        click.echo("Need at least 2 models to compare.", err=True)
        sys.exit(1)

    # Preflight check
    missing = preflight_check(models)
    if missing:
        click.echo(f"Error: Missing CLI tools: {', '.join(missing)}", err=True)
        sys.exit(1)

    # Get diff
    try:
        if branch:
            diff_ref = branch
            diff_content = get_diff(branch, base, cwd=repo)
        else:
            diff_ref = "staged"
            diff_content = get_diff(cwd=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not diff_content.strip():
        click.echo("No changes to compare.")
        sys.exit(0)

    # Build prompt (no spec for simple compare)
    prompt = build_review_prompt(diff_content)

    # Run reviews
    click.echo(f"Running comparison with {', '.join(models)}...", err=True)
    reviews = asyncio.run(review_with_models(models, prompt))

    # Aggregate
    result = aggregate_reviews(diff_ref, reviews)

    # Show only disagreements
    if not result.disagreements:
        click.echo("No disagreements - models agree on all changes.")
    else:
        click.echo(f"Found {len(result.disagreements)} disagreement(s):\n")
        for d in result.disagreements:
            severity = d["severity"]
            change_id = d["change_id"]
            verdicts = d["verdicts"]

            click.echo(f"[{severity}] {change_id}")
            for m, v in verdicts.items():
                click.echo(f"  {m}: {v}")
            click.echo()


@cli.command("check-spec")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to check (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--model",
    "-m",
    default="claude",
    help="Model to use (default: claude)",
)
def check_spec(spec_file, branch, base, repo, model):
    """Check code changes against a specification file."""
    # Preflight check
    missing = preflight_check([model])
    if missing:
        click.echo(f"Error: Missing CLI tool: {model}", err=True)
        sys.exit(1)

    # Get diff
    try:
        if branch:
            diff_content = get_diff(branch, base, cwd=repo)
        else:
            diff_content = get_diff(cwd=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not diff_content.strip():
        click.echo("No changes to check.")
        sys.exit(0)

    # Read spec
    spec_content = read_file_content(spec_file)
    if spec_content is None:
        click.echo(f"Error: Cannot read spec file: {spec_file}", err=True)
        sys.exit(1)

    # Build spec check prompt
    prompt = build_spec_check_prompt(diff_content, spec_content)

    # Run check
    click.echo(f"Checking spec compliance with {model}...", err=True)
    result = asyncio.run(review_with_model(model, prompt))

    # Output raw response for spec check (different format than review)
    click.echo(result.raw_response)


@cli.command()
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to check (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Auto-fix lint issues (black, isort, ruff --fix)",
)
def lint(branch, base, repo, fix):
    """Run lint checks (black, isort, ruff) on changed files."""
    py_files = get_changed_python_files(branch, base, cwd=repo)

    if not py_files:
        click.echo("No Python files changed.")
        sys.exit(0)

    click.echo(f"{'Fixing' if fix else 'Checking'} {len(py_files)} files:")
    for f in py_files:
        click.echo(f"  {f}")
    click.echo()

    if fix:
        fix_result = run_lint_fixes(py_files, cwd=repo)
        if fix_result.total_fixed > 0:
            click.echo("Fixes applied:")
            click.echo(fix_result.summary)
            click.echo()

        # Re-check after fixing
        lint_result = run_lint_checks(py_files, cwd=repo)
        if lint_result.passed:
            click.echo("All lint checks now pass!")
            sys.exit(0)
        else:
            click.echo("Some issues remain (not auto-fixable):\n")
            click.echo(lint_result.summary)
            sys.exit(1)
    else:
        lint_result = run_lint_checks(py_files, cwd=repo)

        if lint_result.passed:
            click.echo("All lint checks passed!")
            sys.exit(0)
        else:
            click.echo("Lint checks failed:\n")
            click.echo(lint_result.summary)
            click.echo("\nRun with --fix to auto-fix issues.")
            sys.exit(1)


@cli.command()
def models():
    """List available models and their status."""
    from .reviewer import MODEL_COMMANDS, check_model_available

    click.echo("Available models:\n")
    for name, cmd in MODEL_COMMANDS.items():
        available = check_model_available(name)
        status = "available" if available else "not found"
        click.echo(f"  {name}: {cmd[0]} [{status}]")


@cli.command()
@click.option(
    "--branch",
    "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--repo",
    "-r",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=".",
    help="Repository directory to analyze (default: current directory)",
)
@click.option(
    "--spec",
    "-s",
    default=None,
    help="Path to spec file for compliance checking",
)
@click.option(
    "--model",
    "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["full", "summary"]),
    default="full",
    help="Output format (default: full)",
)
@click.option(
    "--output-dir",
    "-d",
    type=click.Path(),
    default=None,
    help="Directory to save outputs (report.md + per-model raw responses)",
)
@click.option(
    "--max-iterations",
    "-i",
    default=3,
    help="Maximum observe/review iterations (default: 3)",
)
def auto(branch, base, repo, spec, model, output, output_dir, max_iterations):
    """
    Run automated observe/review loop.

    Automatically gathers observations, runs them, and reviews with context.
    If the review requests additional observations, repeats up to --max-iterations times.

    This is the recommended way to run code review for best results.
    """
    import os
    from datetime import datetime

    from .reviewer import parse_observations

    models = list(model) if model else DEFAULT_MODELS

    # Generate default output_dir if not specified
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # Use sanitized branch name as directory
        branch_id = (branch or "staged").replace("/", "-")
        output_dir = os.path.join("reviews", branch_id, timestamp)
        click.echo(f"Saving review to {output_dir}/", err=True)

    # Preflight check
    missing = preflight_check(models)
    if missing:
        click.echo(f"Error: Missing CLI tools: {', '.join(missing)}", err=True)
        sys.exit(1)

    # Get diff
    try:
        if branch:
            diff_ref = branch
            diff_content = get_diff(branch, base, cwd=repo)
        else:
            diff_ref = "staged"
            diff_content = get_diff(cwd=repo)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not diff_content.strip():
        click.echo("No changes to review.", err=True)
        sys.exit(0)

    # Read spec if provided
    spec_content = None
    if spec:
        spec_content = read_file_content(spec)
        if spec_content is None:
            click.echo(f"Warning: Spec file not found: {spec}", err=True)

    # Use first model for observation gathering
    observe_model = models[0]
    all_observations = {}

    # Create output_dir early so we can save iteration artifacts
    os.makedirs(output_dir, exist_ok=True)

    for iteration in range(1, max_iterations + 1):
        click.echo(f"\n=== Iteration {iteration}/{max_iterations} ===", err=True)
        iter_prefix = f"{iteration:02d}"

        # Observe pass
        click.echo(f"Gathering observations with {observe_model}...", err=True)
        observe_prompt = build_observe_prompt(diff_content)

        # Save observe prompt
        with open(os.path.join(output_dir, f"{iter_prefix}-observe-prompt.txt"), "w") as f:
            f.write(observe_prompt)

        # Run observe model and save response
        observe_response = asyncio.run(run_model(observe_model, observe_prompt))
        with open(os.path.join(output_dir, f"{iter_prefix}-observe-response.txt"), "w") as f:
            f.write(observe_response)

        requested_obs = parse_observe_response(observe_response)

        if requested_obs:
            click.echo(f"Requested {len(requested_obs)} observation(s):", err=True)
            for obs in requested_obs:
                click.echo(f"  - {obs.get('tool')}: {obs.get('name')}", err=True)

            # Run observations and save results
            click.echo("Running observations...", err=True)
            new_obs = asyncio.run(run_observations(requested_obs, repo))
            all_observations.update(new_obs)

            with open(os.path.join(output_dir, f"{iter_prefix}-observations.json"), "w") as f:
                json.dump(new_obs, f, indent=2, default=str)

            click.echo(f"Total observations: {len(all_observations)}", err=True)
        else:
            click.echo("No new observations requested.", err=True)

        # Review pass
        click.echo(f"Running review with {', '.join(models)}...", err=True)
        review_prompt = build_review_prompt(diff_content, spec_content, observations=all_observations if all_observations else None)

        # Save review prompt
        with open(os.path.join(output_dir, f"{iter_prefix}-review-prompt.txt"), "w") as f:
            f.write(review_prompt)

        reviews = asyncio.run(review_with_models(models, review_prompt, observations=all_observations if all_observations else None))

        # Save per-model responses
        for model_review in reviews:
            with open(os.path.join(output_dir, f"{iter_prefix}-{model_review.model}-response.txt"), "w") as f:
                f.write(model_review.raw_response)

        # Check if any model requested more observations
        more_obs_requested = []
        for review_result in reviews:
            obs_requests = parse_observations(review_result.raw_response)
            if obs_requests:
                more_obs_requested.extend(obs_requests)

        if not more_obs_requested:
            click.echo("No additional observations requested. Review complete.", err=True)
            break

        if iteration < max_iterations:
            click.echo(f"Models requested {len(more_obs_requested)} more observation(s), continuing...", err=True)
        else:
            click.echo(f"Max iterations reached. Finalizing review.", err=True)

    # Aggregate and output
    result = aggregate_reviews(diff_ref, reviews, spec)

    if output == "full":
        report = format_aggregate_review(result)
    else:
        report = format_summary(result)

    # Save final report (output_dir already created in loop)
    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    click.echo(f"Saved report to {report_path}", err=True)

    # Save aggregated observations
    if all_observations:
        obs_path = os.path.join(output_dir, "observations.json")
        with open(obs_path, "w", encoding="utf-8") as f:
            json.dump(all_observations, f, indent=2, default=str)
        click.echo(f"Saved observations to {obs_path}", err=True)

    click.echo(report)


@cli.command("install-skill")
@click.option(
    "--skill-dir",
    type=click.Path(),
    default=None,
    help="Target directory for skill file (default: .claude/skills/code-review)",
)
def install_skill(skill_dir):
    """Install the code-review skill file for Claude Code."""
    from pathlib import Path

    from .skill import SKILL_CONTENT

    # Determine target directory
    if skill_dir:
        target_dir = Path(skill_dir)
    else:
        target_dir = Path.cwd() / ".claude" / "skills" / "code-review"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "SKILL.md"

    target_file.write_text(SKILL_CONTENT)
    click.echo(f"Installed skill to {target_file}")


if __name__ == "__main__":
    cli()
