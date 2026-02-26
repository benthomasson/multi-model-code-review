"""Linting checks as pre-model gate."""

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class LintResult:
    """Result of running lint checks."""

    passed: bool
    black_output: str = ""
    isort_output: str = ""
    ruff_output: str = ""

    @property
    def summary(self) -> str:
        """Get summary of lint failures."""
        if self.passed:
            return "All lint checks passed"

        parts = []
        if self.black_output:
            parts.append(f"black: {self.black_output.strip()}")
        if self.isort_output:
            parts.append(f"isort: {self.isort_output.strip()}")
        if self.ruff_output:
            parts.append(f"ruff: {self.ruff_output.strip()}")
        return "\n".join(parts)


def check_linter_available(name: str) -> bool:
    """Check if a linter is available."""
    return shutil.which(name) is not None


def run_black_check(paths: list[str]) -> tuple[bool, str]:
    """Run black --check on paths."""
    if not paths:
        return True, ""

    if not check_linter_available("black"):
        return True, ""  # Skip if not installed

    result = subprocess.run(
        ["black", "--check", "--quiet"] + paths,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, ""
    else:
        # Get list of files that would be reformatted
        result_verbose = subprocess.run(
            ["black", "--check"] + paths,
            capture_output=True,
            text=True,
        )
        return False, result_verbose.stderr or result_verbose.stdout


def run_isort_check(paths: list[str]) -> tuple[bool, str]:
    """Run isort --check on paths."""
    if not paths:
        return True, ""

    if not check_linter_available("isort"):
        return True, ""  # Skip if not installed

    result = subprocess.run(
        ["isort", "--check-only", "--quiet"] + paths,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, ""
    else:
        # Get list of files that would be reformatted
        result_verbose = subprocess.run(
            ["isort", "--check-only", "--diff"] + paths,
            capture_output=True,
            text=True,
        )
        return False, result_verbose.stdout or result_verbose.stderr


def run_ruff_check(paths: list[str]) -> tuple[bool, str]:
    """Run ruff check on paths."""
    if not paths:
        return True, ""

    if not check_linter_available("ruff"):
        return True, ""  # Skip if not installed

    result = subprocess.run(
        ["ruff", "check"] + paths,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, ""
    else:
        return False, result.stdout or result.stderr


def run_lint_checks(paths: list[str]) -> LintResult:
    """
    Run all lint checks on the given paths.

    Args:
        paths: List of file/directory paths to check

    Returns:
        LintResult with pass/fail status and outputs
    """
    black_passed, black_output = run_black_check(paths)
    isort_passed, isort_output = run_isort_check(paths)
    ruff_passed, ruff_output = run_ruff_check(paths)

    return LintResult(
        passed=black_passed and isort_passed and ruff_passed,
        black_output=black_output if not black_passed else "",
        isort_output=isort_output if not isort_passed else "",
        ruff_output=ruff_output if not ruff_passed else "",
    )


def get_changed_python_files(ref: str | None = None, base: str | None = None) -> list[str]:
    """
    Get list of changed Python files from git diff.

    Args:
        ref: Branch or commit to diff. If None, uses staged changes.
        base: Base branch to diff against (default: main)

    Returns:
        List of changed .py file paths
    """
    if ref is None:
        cmd = ["git", "diff", "--staged", "--name-only", "--diff-filter=ACMR"]
    else:
        base = base or "main"
        cmd = ["git", "diff", f"{base}...{ref}", "--name-only", "--diff-filter=ACMR"]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return []

    files = [f for f in result.stdout.strip().split("\n") if f and f.endswith(".py")]
    return files
