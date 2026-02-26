"""Linting checks as pre-model gate."""

import subprocess
import sys
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
    """Check if a linter module is available via python -m."""
    result = subprocess.run(
        [sys.executable, "-m", name, "--version"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def run_black_check(paths: list[str]) -> tuple[bool, str]:
    """Run black --check on paths."""
    if not paths:
        return True, ""

    if not check_linter_available("black"):
        return True, ""  # Skip if not installed

    result = subprocess.run(
        [sys.executable, "-m", "black", "--check", "--quiet"] + paths,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, ""
    else:
        # Get list of files that would be reformatted
        result_verbose = subprocess.run(
            [sys.executable, "-m", "black", "--check"] + paths,
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
        [sys.executable, "-m", "isort", "--check-only", "--quiet"] + paths,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, ""
    else:
        # Get list of files that would be reformatted
        result_verbose = subprocess.run(
            [sys.executable, "-m", "isort", "--check-only", "--diff"] + paths,
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
        [sys.executable, "-m", "ruff", "check"] + paths,
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


@dataclass
class FixResult:
    """Result of running lint fixes."""

    black_fixed: int = 0
    isort_fixed: int = 0
    ruff_fixed: int = 0

    @property
    def total_fixed(self) -> int:
        return self.black_fixed + self.isort_fixed + self.ruff_fixed

    @property
    def summary(self) -> str:
        parts = []
        if self.black_fixed:
            parts.append(f"black: {self.black_fixed} files reformatted")
        if self.isort_fixed:
            parts.append(f"isort: {self.isort_fixed} files fixed")
        if self.ruff_fixed:
            parts.append(f"ruff: {self.ruff_fixed} fixes applied")
        return "\n".join(parts) if parts else "No fixes needed"


def run_black_fix(paths: list[str]) -> int:
    """Run black to fix formatting issues."""
    if not paths or not check_linter_available("black"):
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "black"] + paths,
        capture_output=True,
        text=True,
    )

    # Count reformatted files from output
    output = result.stderr or result.stdout
    count = output.count("reformatted")
    return count


def run_isort_fix(paths: list[str]) -> int:
    """Run isort to fix import ordering."""
    if not paths or not check_linter_available("isort"):
        return 0

    # First check how many need fixing
    check_result = subprocess.run(
        [sys.executable, "-m", "isort", "--check-only"] + paths,
        capture_output=True,
        text=True,
    )

    if check_result.returncode == 0:
        return 0

    # Count files that would be changed
    diff_result = subprocess.run(
        [sys.executable, "-m", "isort", "--check-only", "--diff"] + paths,
        capture_output=True,
        text=True,
    )
    # Count unique file headers in diff output
    count = diff_result.stdout.count("---")

    # Now fix them
    subprocess.run(
        [sys.executable, "-m", "isort"] + paths,
        capture_output=True,
        text=True,
    )

    return count


def run_ruff_fix(paths: list[str]) -> int:
    """Run ruff --fix to auto-fix linting issues."""
    if not paths or not check_linter_available("ruff"):
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--fix"] + paths,
        capture_output=True,
        text=True,
    )

    # Parse "Found X errors (Y fixed, Z remaining)"
    output = result.stdout or result.stderr
    if "fixed" in output.lower():
        import re

        match = re.search(r"(\d+) fixed", output)
        if match:
            return int(match.group(1))
    return 0


def run_lint_fixes(paths: list[str]) -> FixResult:
    """
    Run all lint fixers on the given paths.

    Order: isort (imports) → ruff (remove unused, etc) → black (final formatting).
    Black runs last to clean up any artifacts from other fixers.

    Args:
        paths: List of file/directory paths to fix

    Returns:
        FixResult with counts of fixes applied
    """
    isort_fixed = run_isort_fix(paths)
    ruff_fixed = run_ruff_fix(paths)
    black_fixed = run_black_fix(paths)

    return FixResult(
        black_fixed=black_fixed,
        isort_fixed=isort_fixed,
        ruff_fixed=ruff_fixed,
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
