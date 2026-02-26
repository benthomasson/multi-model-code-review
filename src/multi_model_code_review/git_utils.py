"""Git utilities for extracting diffs."""

import subprocess


def get_diff(
    ref: str | None = None,
    base: str | None = None,
    cwd: str | None = None,
    context_lines: int = 10,
) -> str:
    """
    Get git diff for review.

    Args:
        ref: Branch or commit to diff. If None, uses staged changes.
        base: Base branch to diff against (default: main)
        cwd: Working directory to run git in (default: current directory)
        context_lines: Number of context lines around changes (default: 10)

    Returns:
        Git diff output as string

    Raises:
        RuntimeError: If git command fails
    """
    context_arg = f"-U{context_lines}"

    if ref is None:
        # Staged changes
        cmd = ["git", "diff", "--staged", context_arg]
    else:
        # Diff between base and ref
        # Default to origin/main to avoid stale local main issues
        if base is None:
            # Check if origin/main exists, fall back to main
            check = subprocess.run(
                ["git", "rev-parse", "--verify", "origin/main"],
                capture_output=True,
                cwd=cwd,
            )
            base = "origin/main" if check.returncode == 0 else "main"
        cmd = ["git", "diff", context_arg, f"{base}...{ref}"]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)

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


def extract_changed_files(diff_content: str) -> list[str]:
    """
    Extract file paths from a git diff.

    Args:
        diff_content: Git diff output

    Returns:
        List of file paths that were changed
    """
    import re

    files = []
    # Match "+++ b/path/to/file" lines
    for line in diff_content.split("\n"):
        if line.startswith("+++ b/"):
            path = line[6:]  # Remove "+++ b/" prefix
            if path != "/dev/null":  # Exclude deleted files
                files.append(path)
    return files
