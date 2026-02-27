"""Tests for observation tools."""

import pytest

from multi_model_code_review.observations import (
    exception_hierarchy,
    raises_analysis,
    call_graph,
    run_observations,
    OBSERVATION_TOOLS,
)


@pytest.mark.asyncio
async def test_exception_hierarchy_httpx():
    """Test exception hierarchy for httpx.TransportError."""
    # Skip if httpx not installed
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")

    result = await exception_hierarchy("httpx.TransportError")

    assert "error" not in result
    assert result["class"] == "httpx.TransportError"
    assert "mro" in result
    assert "subclasses" in result

    # TransportError should have these subclasses
    subclass_names = [s.split(".")[-1] for s in result["subclasses"]]
    assert "ConnectError" in subclass_names
    assert "ReadError" in subclass_names
    assert "WriteError" in subclass_names


@pytest.mark.asyncio
async def test_exception_hierarchy_builtin():
    """Test exception hierarchy for built-in exceptions."""
    result = await exception_hierarchy("builtins.OSError")

    assert "error" not in result
    assert "ConnectionError" in str(result["subclasses"])


@pytest.mark.asyncio
async def test_exception_hierarchy_bare_builtin():
    """Test exception hierarchy for bare builtin name (no module prefix)."""
    result = await exception_hierarchy("ValueError")

    assert "error" not in result
    assert result["class"] == "ValueError"
    assert "mro" in result


@pytest.mark.asyncio
async def test_exception_hierarchy_invalid():
    """Test exception hierarchy with invalid class."""
    result = await exception_hierarchy("nonexistent.FakeError")

    assert "error" in result


@pytest.mark.asyncio
async def test_raises_analysis(tmp_path):
    """Test raises analysis on a sample file."""
    # Create a test file
    test_file = tmp_path / "sample.py"
    test_file.write_text("""
def my_function():
    if something:
        raise ValueError("bad value")
    try:
        do_something()
    except Exception:
        raise RuntimeError("failed")
""")

    result = await raises_analysis(str(test_file), "my_function")

    assert "error" not in result
    assert "ValueError" in result["explicit_raises"]
    assert "RuntimeError" in result["explicit_raises"]
    assert "do_something" in result["calls"]


@pytest.mark.asyncio
async def test_call_graph(tmp_path):
    """Test call graph analysis."""
    test_file = tmp_path / "sample.py"
    test_file.write_text("""
def my_function():
    helper()
    self.method()
    module.function()
    result = compute(x, y)
    return result
""")

    result = await call_graph(str(test_file), "my_function")

    assert "error" not in result
    call_names = [c["name"] for c in result["calls"]]
    assert "helper" in call_names
    assert "self.method" in call_names
    assert "module.function" in call_names
    assert "compute" in call_names


@pytest.mark.asyncio
async def test_run_observations():
    """Test running multiple observations."""
    observations = [
        {
            "name": "oserror_hierarchy",
            "tool": "exception_hierarchy",
            "params": {"class_name": "builtins.OSError"},
        },
    ]

    results = await run_observations(observations, "/tmp")

    assert "oserror_hierarchy" in results
    assert "error" not in results["oserror_hierarchy"]


@pytest.mark.asyncio
async def test_run_observations_invalid_tool():
    """Test handling of invalid tool name."""
    observations = [
        {
            "name": "bad_obs",
            "tool": "nonexistent_tool",
            "params": {},
        },
    ]

    results = await run_observations(observations, "/tmp")

    assert "bad_obs" in results
    assert "error" in results["bad_obs"]


def test_observation_tools_registry():
    """Test that all expected tools are registered."""
    expected_tools = [
        "exception_hierarchy",
        "raises_analysis",
        "call_graph",
        "find_usages",
        "git_blame",
        "test_coverage",
    ]

    for tool in expected_tools:
        assert tool in OBSERVATION_TOOLS
