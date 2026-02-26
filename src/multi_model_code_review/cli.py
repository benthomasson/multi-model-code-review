"""Command-line interface for multi-model code review."""

import asyncio
import sys

import click

from . import Verdict
from .aggregator import aggregate_reviews
from .git_utils import get_diff, read_file_content
from .prompts import build_review_prompt, build_spec_check_prompt
from .report import format_aggregate_review, format_summary
from .reviewer import preflight_check, review_with_models

DEFAULT_MODELS = ["claude", "gemini"]


@click.group()
@click.version_option()
def cli():
    """Multi-model code review - AI-first review using multiple models."""
    pass


@cli.command()
@click.option(
    "--branch", "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--spec", "-s",
    default=None,
    help="Path to spec file for compliance checking",
)
@click.option(
    "--model", "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
@click.option(
    "--output", "-o",
    type=click.Choice(["full", "summary"]),
    default="full",
    help="Output format (default: full)",
)
def review(branch, base, spec, model, output):
    """Run code review with multiple models."""
    models = list(model) if model else DEFAULT_MODELS

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
            diff_content = get_diff(branch, base)
        else:
            diff_ref = "staged"
            diff_content = get_diff()
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

    # Build prompt
    prompt = build_review_prompt(diff_content, spec_content)

    # Run reviews
    click.echo(f"Running review with {', '.join(models)}...", err=True)
    reviews = asyncio.run(review_with_models(models, prompt))

    # Aggregate
    result = aggregate_reviews(diff_ref, reviews, spec)

    # Output
    if output == "full":
        click.echo(format_aggregate_review(result))
    else:
        click.echo(format_summary(result))


@cli.command()
@click.option(
    "--branch", "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--spec", "-s",
    default=None,
    help="Path to spec file for compliance checking",
)
@click.option(
    "--model", "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
def gate(branch, base, spec, model):
    """
    Run review and exit with code based on result.

    Exit codes:
    - 0: PASS (all models pass)
    - 1: CONCERN (at least one concern, no blocks)
    - 2: BLOCK (at least one model blocks)
    """
    models = list(model) if model else DEFAULT_MODELS

    # Preflight check
    missing = preflight_check(models)
    if missing:
        click.echo(f"Error: Missing CLI tools: {', '.join(missing)}", err=True)
        sys.exit(2)  # Block on missing tools

    # Get diff
    try:
        if branch:
            diff_ref = branch
            diff_content = get_diff(branch, base)
        else:
            diff_ref = "staged"
            diff_content = get_diff()
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
    "--branch", "-b",
    default=None,
    help="Branch to review (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--model", "-m",
    multiple=True,
    help="Models to use (default: claude, gemini)",
)
def compare(branch, base, model):
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
            diff_content = get_diff(branch, base)
        else:
            diff_ref = "staged"
            diff_content = get_diff()
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
    "--branch", "-b",
    default=None,
    help="Branch to check (default: staged changes)",
)
@click.option(
    "--base",
    default="main",
    help="Base branch to diff against (default: main)",
)
@click.option(
    "--model", "-m",
    default="claude",
    help="Model to use (default: claude)",
)
def check_spec(spec_file, branch, base, model):
    """Check code changes against a specification file."""
    # Preflight check
    missing = preflight_check([model])
    if missing:
        click.echo(f"Error: Missing CLI tool: {model}", err=True)
        sys.exit(1)

    # Get diff
    try:
        if branch:
            diff_content = get_diff(branch, base)
        else:
            diff_content = get_diff()
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
    from .reviewer import review_with_model
    result = asyncio.run(review_with_model(model, prompt))

    # Output raw response for spec check (different format than review)
    click.echo(result.raw_response)


@cli.command()
def models():
    """List available models and their status."""
    from .reviewer import MODEL_COMMANDS, check_model_available

    click.echo("Available models:\n")
    for name, cmd in MODEL_COMMANDS.items():
        available = check_model_available(name)
        status = "available" if available else "not found"
        click.echo(f"  {name}: {cmd[0]} [{status}]")


if __name__ == "__main__":
    cli()
