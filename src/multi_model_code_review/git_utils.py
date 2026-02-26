"""Git utilities for extracting diffs."""

import subprocess


def get_diff(ref: str | None = None, base: str | None = None) -> str:
    """
    Get git diff for review.

    Args:
        ref: Branch or commit to diff. If None, uses staged changes.
        base: Base branch to diff against (default: main)

    Returns:
        Git diff output as string

    Raises:
        RuntimeError: If git command fails
    """
    if ref is None:
        # Staged changes
        cmd = ["git", "diff", "--staged"]
    elif base:
        # Diff between base and ref
        cmd = ["git", "diff", f"{base}...{ref}"]
    else:
        # Diff between main and ref
        cmd = ["git", "diff", f"main...{ref}"]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Git diff failed: {result.stderr}")

    return result.stdout


def get_current_branch() -> str:
    """Get the current git branch name."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Git branch failed: {result.stderr}")

    return result.stdout.strip()


def get_changed_files(ref: str | None = None, base: str | None = None) -> list[str]:
    """
    Get list of changed files.

    Args:
        ref: Branch or commit to diff. If None, uses staged changes.
        base: Base branch to diff against (default: main)

    Returns:
        List of changed file paths
    """
    if ref is None:
        cmd = ["git", "diff", "--staged", "--name-only"]
    elif base:
        cmd = ["git", "diff", f"{base}...{ref}", "--name-only"]
    else:
        cmd = ["git", "diff", f"main...{ref}", "--name-only"]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Git diff failed: {result.stderr}")

    return [f for f in result.stdout.strip().split("\n") if f]


def read_file_content(path: str) -> str | None:
    """
    Read file content, returning None if file doesn't exist.

    Args:
        path: Path to file

    Returns:
        File content or None
    """
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None
