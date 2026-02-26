"""
Observation tools for code review.

Inspired by ftl2-ai-loop's observe pattern, these tools allow reviewers
to request additional information about the code being reviewed.

The reviewer can include an "observe" field in their response:
    {
        "verdict": "CONCERN",
        "reasoning": "Need to verify exception coverage",
        "observe": [
            {"name": "httpx_errors", "tool": "exception_hierarchy", "params": {"class_name": "httpx.TransportError"}}
        ]
    }

The review loop will run the requested observations and re-invoke the
reviewer with the additional context.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from typing import Any


async def exception_hierarchy(class_name: str, repo_path: str | None = None) -> dict[str, Any]:
    """
    Show exception class hierarchy (MRO and subclasses).

    Args:
        class_name: Fully qualified class name (e.g., "httpx.TransportError")
        repo_path: Optional repo path (unused, for interface consistency)

    Returns:
        Dict with class name, MRO, and all subclasses (recursive)
    """
    try:
        module_name, cls_name = class_name.rsplit(".", 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, cls_name)

        def get_all_subclasses(c: type) -> list[str]:
            """Recursively get all subclasses."""
            result = []
            for sub in c.__subclasses__():
                result.append(f"{sub.__module__}.{sub.__name__}")
                result.extend(get_all_subclasses(sub))
            return result

        return {
            "class": class_name,
            "mro": [f"{c.__module__}.{c.__name__}" for c in cls.__mro__ if c is not object],
            "subclasses": get_all_subclasses(cls),
            "doc": cls.__doc__[:200] if cls.__doc__ else None,
        }
    except Exception as e:
        return {"error": str(e), "class": class_name}


async def raises_analysis(file_path: str, function_name: str, repo_path: str | None = None) -> dict[str, Any]:
    """
    Static analysis of what exceptions a function might raise.

    Args:
        file_path: Path to the Python file (relative to repo_path or absolute)
        function_name: Name of the function to analyze
        repo_path: Base path for relative file paths

    Returns:
        Dict with explicit raises and called functions that might raise
    """
    try:
        if repo_path and not Path(file_path).is_absolute():
            full_path = Path(repo_path) / file_path
        else:
            full_path = Path(file_path)

        source = full_path.read_text()
        tree = ast.parse(source)

        raises: list[str] = []
        calls: list[str] = []

        # Find the function
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == function_name:
                    # Find all raise statements
                    for child in ast.walk(node):
                        if isinstance(child, ast.Raise):
                            if child.exc:
                                if isinstance(child.exc, ast.Call):
                                    if isinstance(child.exc.func, ast.Name):
                                        raises.append(child.exc.func.id)
                                    elif isinstance(child.exc.func, ast.Attribute):
                                        raises.append(child.exc.func.attr)
                                elif isinstance(child.exc, ast.Name):
                                    raises.append(child.exc.id)

                        # Find all function calls (potential raise sources)
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Name):
                                calls.append(child.func.id)
                            elif isinstance(child.func, ast.Attribute):
                                calls.append(child.func.attr)

        return {
            "function": function_name,
            "file": str(file_path),
            "explicit_raises": list(set(raises)),
            "calls": list(set(calls))[:20],  # Limit to avoid noise
        }
    except Exception as e:
        return {"error": str(e), "function": function_name}


async def call_graph(file_path: str, function_name: str, repo_path: str | None = None) -> dict[str, Any]:
    """
    Build call graph for a function.

    Args:
        file_path: Path to the Python file
        function_name: Name of the function to analyze
        repo_path: Base path for relative file paths

    Returns:
        Dict with functions called by this function
    """
    try:
        if repo_path and not Path(file_path).is_absolute():
            full_path = Path(repo_path) / file_path
        else:
            full_path = Path(file_path)

        source = full_path.read_text()
        tree = ast.parse(source)

        calls: list[dict[str, Any]] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == function_name:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            call_info: dict[str, Any] = {"line": child.lineno}

                            if isinstance(child.func, ast.Name):
                                call_info["name"] = child.func.id
                            elif isinstance(child.func, ast.Attribute):
                                # e.g., self.method() or module.func()
                                if isinstance(child.func.value, ast.Name):
                                    call_info["name"] = f"{child.func.value.id}.{child.func.attr}"
                                else:
                                    call_info["name"] = child.func.attr

                            if "name" in call_info:
                                calls.append(call_info)

        # Deduplicate by name, keep first occurrence
        seen = set()
        unique_calls = []
        for call in calls:
            if call["name"] not in seen:
                seen.add(call["name"])
                unique_calls.append(call)

        return {
            "function": function_name,
            "file": str(file_path),
            "calls": unique_calls,
        }
    except Exception as e:
        return {"error": str(e), "function": function_name}


async def find_usages(symbol: str, repo_path: str) -> dict[str, Any]:
    """
    Find usages of a symbol in the codebase.

    Args:
        symbol: Symbol to search for (class name, function name, etc.)
        repo_path: Repository path to search in

    Returns:
        Dict with files and line numbers where the symbol is used
    """
    try:
        import subprocess

        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", symbol, repo_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        usages = []
        for line in result.stdout.strip().split("\n"):
            if line and ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    usages.append({
                        "file": parts[0].replace(repo_path + "/", ""),
                        "line": int(parts[1]),
                        "text": parts[2].strip()[:100],
                    })

        return {
            "symbol": symbol,
            "usages": usages[:30],  # Limit results
            "total_count": len(usages),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


async def git_blame(file_path: str, start_line: int, end_line: int, repo_path: str) -> dict[str, Any]:
    """
    Get git blame information for a range of lines.

    Args:
        file_path: Path to the file (relative to repo)
        start_line: Starting line number
        end_line: Ending line number
        repo_path: Repository path

    Returns:
        Dict with blame information per line
    """
    try:
        import subprocess

        result = subprocess.run(
            ["git", "-C", repo_path, "blame", "-L", f"{start_line},{end_line}", "--porcelain", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {"error": result.stderr, "file": file_path}

        # Parse porcelain format
        lines = result.stdout.strip().split("\n")
        blame_info = []
        current_commit = None
        current_author = None

        for line in lines:
            if line.startswith("author "):
                current_author = line[7:]
            elif line.startswith("\t"):
                if current_commit and current_author:
                    blame_info.append({
                        "commit": current_commit[:8],
                        "author": current_author,
                        "code": line[1:][:60],
                    })
            elif " " in line and len(line.split()[0]) == 40:
                current_commit = line.split()[0]

        return {
            "file": file_path,
            "range": f"{start_line}-{end_line}",
            "blame": blame_info,
        }
    except Exception as e:
        return {"error": str(e), "file": file_path}


async def test_coverage(file_path: str, repo_path: str) -> dict[str, Any]:
    """
    Find tests that cover a given file.

    Args:
        file_path: Path to the source file
        repo_path: Repository path

    Returns:
        Dict with test files that likely test this module
    """
    try:
        # Extract module name from path
        path = Path(file_path)
        module_name = path.stem  # e.g., "client" from "client.py"

        # Search for test files
        test_patterns = [
            f"test_{module_name}.py",
            f"{module_name}_test.py",
            f"test_{module_name}*.py",
        ]

        import subprocess

        tests_found = []
        for pattern in test_patterns:
            result = subprocess.run(
                ["find", repo_path, "-name", pattern, "-path", "*/tests/*"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for test_file in result.stdout.strip().split("\n"):
                if test_file:
                    tests_found.append(test_file.replace(repo_path + "/", ""))

        return {
            "source_file": file_path,
            "test_files": list(set(tests_found)),
        }
    except Exception as e:
        return {"error": str(e), "file": file_path}


# Registry of all observation tools
OBSERVATION_TOOLS: dict[str, Any] = {
    "exception_hierarchy": exception_hierarchy,
    "raises_analysis": raises_analysis,
    "call_graph": call_graph,
    "find_usages": find_usages,
    "git_blame": git_blame,
    "test_coverage": test_coverage,
}


async def run_observation(name: str, tool: str, params: dict[str, Any], repo_path: str) -> dict[str, Any]:
    """
    Run a single observation tool.

    Args:
        name: Name to assign to the result
        tool: Tool name from OBSERVATION_TOOLS
        params: Parameters for the tool
        repo_path: Repository path

    Returns:
        Dict with the observation result
    """
    if tool not in OBSERVATION_TOOLS:
        return {"name": name, "result": {"error": f"Unknown tool: {tool}"}}

    tool_func = OBSERVATION_TOOLS[tool]

    # Inject repo_path if the tool accepts it
    if "repo_path" not in params:
        params["repo_path"] = repo_path

    result = await tool_func(**params)
    return {"name": name, "tool": tool, "result": result}


async def run_observations(observations: list[dict[str, Any]], repo_path: str) -> dict[str, Any]:
    """
    Run multiple observations and collect results.

    Args:
        observations: List of observation requests
        repo_path: Repository path

    Returns:
        Dict mapping observation names to results
    """
    results = {}
    for obs in observations:
        name = obs.get("name", "unnamed")
        tool = obs.get("tool")
        params = obs.get("params", {})

        if not tool:
            results[name] = {"error": "No tool specified"}
            continue

        result = await run_observation(name, tool, params, repo_path)
        results[name] = result["result"]

    return results
