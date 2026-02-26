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
    else:
        # Diff between base and ref (base defaults to main in CLI)
        base = base or "main"
        cmd = ["git", "diff", f"{base}...{ref}"]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Git diff failed: {result.stderr}")

    return result.stdout


def read_file_content(path: str) -> str | None:
    """
    Read file content, returning None if file doesn't exist.

    Args:
        path: Path to file

    Returns:
        File content or None
    """
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
