"""Model invocation and response parsing for code review."""

import asyncio
import os
import re
import shutil
from typing import Any

from . import (
    ChangeVerdict,
    Correctness,
    Integration,
    ModelReview,
    SpecCompliance,
    TestCoverage,
    Verdict,
)

# Model CLI commands - extend this dict to add new models
# Note: gemini requires empty string after -p to read prompt from stdin
MODEL_COMMANDS: dict[str, list[str]] = {
    "claude": ["claude", "-p"],
    "gemini": ["gemini", "-p", ""],  # empty arg is workaround for stdin input
}

# Default timeout for model invocation (5 minutes)
DEFAULT_TIMEOUT = 300


def check_model_available(model: str) -> bool:
    """Check if a model's CLI is available."""
    if model not in MODEL_COMMANDS:
        return False
    cmd = MODEL_COMMANDS[model][0]
    return shutil.which(cmd) is not None


def preflight_check(models: list[str]) -> list[str]:
    """Check which models are available, return list of missing ones."""
    missing = []
    for model in models:
        if not check_model_available(model):
            missing.append(model)
    return missing


async def run_model(model: str, prompt: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """
    Invoke model via CLI, piping prompt through stdin.

    Args:
        model: Model name (must be in MODEL_COMMANDS)
        prompt: Full prompt text to send
        timeout: Timeout in seconds

    Returns:
        Model's response text

    Raises:
        ValueError: If model not supported
        TimeoutError: If model doesn't respond in time
        RuntimeError: If model invocation fails
    """
    if model not in MODEL_COMMANDS:
        raise ValueError(f"Unknown model: {model}. Available: {list(MODEL_COMMANDS.keys())}")

    cmd = MODEL_COMMANDS[model]

    # Remove CLAUDECODE env var to allow nested claude invocation
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Model {model} timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(f"Model {model} failed: {stderr.decode()}")

    return stdout.decode()


def parse_verdict(text: str) -> Verdict:
    """Parse verdict string to enum."""
    text = text.strip().upper()
    if text == "PASS":
        return Verdict.PASS
    elif text == "CONCERN":
        return Verdict.CONCERN
    elif text == "BLOCK":
        return Verdict.BLOCK
    else:
        # Conservative default
        return Verdict.CONCERN


def parse_correctness(text: str) -> Correctness | None:
    """Parse correctness string to enum."""
    text = text.strip().upper()
    if text == "VALID":
        return Correctness.VALID
    elif text == "QUESTIONABLE":
        return Correctness.QUESTIONABLE
    elif text == "BROKEN":
        return Correctness.BROKEN
    return None


def parse_spec_compliance(text: str) -> SpecCompliance | None:
    """Parse spec compliance string to enum."""
    text = text.strip().upper()
    if text == "MEETS":
        return SpecCompliance.MEETS
    elif text == "PARTIAL":
        return SpecCompliance.PARTIAL
    elif text == "VIOLATES":
        return SpecCompliance.VIOLATES
    elif text in ("N/A", "NA"):
        return SpecCompliance.NA
    return None


def parse_test_coverage(text: str) -> TestCoverage | None:
    """Parse test coverage string to enum."""
    text = text.strip().upper()
    if text == "COVERED":
        return TestCoverage.COVERED
    elif text == "PARTIAL":
        return TestCoverage.PARTIAL
    elif text == "UNTESTED":
        return TestCoverage.UNTESTED
    return None


def parse_integration(text: str) -> Integration | None:
    """Parse integration string to enum."""
    text = text.strip().upper()
    if text == "WIRED":
        return Integration.WIRED
    elif text == "PARTIAL":
        return Integration.PARTIAL
    elif text == "MISSING":
        return Integration.MISSING
    return None


# Pattern to match change verdicts in model output
CHANGE_PATTERN = re.compile(
    r"###\s+(.+?)\s*\n"
    r"VERDICT:\s*(PASS|CONCERN|BLOCK)\s*\n"
    r"(?:CORRECTNESS:\s*(\w+)\s*\n)?"
    r"(?:SPEC_COMPLIANCE:\s*([^\n]+)\s*\n)?"
    r"(?:TEST_COVERAGE:\s*(\w+)\s*\n)?"
    r"(?:INTEGRATION:\s*(\w+)\s*\n)?"
    r"REASONING:\s*(.*?)(?=\n---|\n###|\n##|$)",
    re.DOTALL | re.IGNORECASE,
)


def parse_review_response(model: str, response: str) -> ModelReview:
    """
    Parse model response into structured review.

    Args:
        model: Model name
        response: Raw model response text

    Returns:
        ModelReview with parsed changes
    """
    changes: list[ChangeVerdict] = []

    for match in CHANGE_PATTERN.finditer(response):
        change_id = match.group(1).strip()
        verdict = parse_verdict(match.group(2))
        correctness = parse_correctness(match.group(3)) if match.group(3) else None
        spec_compliance = parse_spec_compliance(match.group(4)) if match.group(4) else None
        test_coverage = parse_test_coverage(match.group(5)) if match.group(5) else None
        integration = parse_integration(match.group(6)) if match.group(6) else None
        reasoning = match.group(7).strip() if match.group(7) else ""

        changes.append(
            ChangeVerdict(
                change_id=change_id,
                verdict=verdict,
                correctness=correctness,
                spec_compliance=spec_compliance,
                test_coverage=test_coverage,
                integration=integration,
                reasoning=reasoning,
            )
        )

    # Determine overall gate - BLOCK > CONCERN > PASS
    gate = Verdict.PASS
    for change in changes:
        if change.verdict == Verdict.BLOCK:
            gate = Verdict.BLOCK
            break
        elif change.verdict == Verdict.CONCERN:
            gate = Verdict.CONCERN

    # If no changes parsed, default to CONCERN (conservative)
    if not changes:
        gate = Verdict.CONCERN

    return ModelReview(
        model=model,
        gate=gate,
        changes=changes,
        raw_response=response,
    )


async def review_with_model(model: str, prompt: str) -> ModelReview:
    """
    Run review with a single model and parse response.

    Args:
        model: Model name
        prompt: Review prompt

    Returns:
        Parsed ModelReview
    """
    try:
        response = await run_model(model, prompt)
        return parse_review_response(model, response)
    except Exception as e:
        # On error, return BLOCK with error message
        return ModelReview(
            model=model,
            gate=Verdict.BLOCK,
            changes=[
                ChangeVerdict(
                    change_id="ERROR",
                    verdict=Verdict.BLOCK,
                    reasoning=f"Model invocation failed: {e}",
                )
            ],
            raw_response=str(e),
        )


async def review_with_models(models: list[str], prompt: str) -> list[ModelReview]:
    """
    Run review with multiple models concurrently.

    Args:
        models: List of model names
        prompt: Review prompt (same for all models)

    Returns:
        List of ModelReview, one per model
    """
    tasks = [review_with_model(model, prompt) for model in models]
    return await asyncio.gather(*tasks)
