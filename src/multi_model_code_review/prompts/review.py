"""General code review prompt."""

CODE_REVIEW_PROMPT = """You are a senior code reviewer. Review the following code changes.

{spec_section}

## Code Changes

```diff
{diff_content}
```

## Instructions

For each significant change (new file, modified function, etc.), provide a structured verdict.

Use this exact format for each change:

### <file_path or file_path:function_name>
VERDICT: PASS | CONCERN | BLOCK
CORRECTNESS: VALID | QUESTIONABLE | BROKEN
SPEC_COMPLIANCE: MEETS | PARTIAL | VIOLATES | N/A
TEST_COVERAGE: COVERED | PARTIAL | UNTESTED
INTEGRATION: WIRED | PARTIAL | MISSING
REASONING: <brief explanation of your assessment>
---

## Review Criteria

1. **CORRECTNESS**: Does the code do what it claims? Is the logic sound?
   - VALID: Logic is correct, no bugs apparent
   - QUESTIONABLE: Logic may have edge cases or unclear behavior
   - BROKEN: Clear bugs or incorrect behavior

2. **SPEC_COMPLIANCE**: Does it meet MUST requirements from the spec?
   - MEETS: All relevant spec requirements satisfied
   - PARTIAL: Some requirements met, others missing or incomplete
   - VIOLATES: Contradicts spec requirements
   - N/A: No spec provided or not applicable

3. **TEST_COVERAGE**: Are there tests for the new/changed code?
   - COVERED: Tests exist and cover the changes
   - PARTIAL: Some tests exist but coverage is incomplete
   - UNTESTED: No tests for the changes

4. **INTEGRATION**: Are callers updated? Is the feature usable end-to-end?
   - WIRED: Feature is fully integrated and usable
   - PARTIAL: Interface exists but callers not updated, or integration incomplete
   - MISSING: No integration with existing code

## Verdict Guidelines

- **BLOCK**: Security issues, broken functionality, spec violations, or missing critical integration
- **CONCERN**: Missing tests, partial integration, questionable patterns, or unclear logic
- **PASS**: Correct, tested, well-integrated code

## Important

- Focus on actual issues, not style preferences
- If a method signature is added but callers aren't updated, that's PARTIAL integration
- Be specific in reasoning - reference line numbers or function names
- When in doubt, use CONCERN rather than PASS

## Self-Review

After completing your review, add a brief self-assessment:

### SELF_REVIEW
CONFIDENCE: HIGH | MEDIUM | LOW
LIMITATIONS: <what context were you missing that affected review quality?>
---

Examples of limitations:
- "Could not see full class to verify no other methods access the modified field"
- "Test file not included in diff - cannot verify coverage claims"
- "Spec file referenced but not provided"

## Observation Requests

If you need more information to render a confident verdict, you can request observations.
Available observation tools:

| Tool | Purpose | Example params |
|------|---------|----------------|
| `exception_hierarchy` | Show exception class MRO and all subclasses | `{{"class_name": "httpx.TransportError"}}` |
| `raises_analysis` | Static analysis of what a function raises | `{{"file_path": "src/client.py", "function_name": "authenticate"}}` |
| `call_graph` | What functions does a function call | `{{"file_path": "src/client.py", "function_name": "authenticate"}}` |
| `find_usages` | Where is a symbol used in the codebase | `{{"symbol": "DataverseClient"}}` |
| `git_blame` | Who changed specific lines | `{{"file_path": "src/client.py", "start_line": 100, "end_line": 120}}` |
| `test_coverage` | Find tests for a source file | `{{"file_path": "src/client.py"}}` |

To request observations, add this section:

### OBSERVATIONS
```json
[
  {{"name": "result_name", "tool": "tool_name", "params": {{...}}}}
]
```
---

The system will run your observations and re-invoke you with the results. Only request
observations when you genuinely need more context - the review will iterate up to 3 times.

{observations_section}

## Feature Requests

If this review tool could be improved to help you do a better job, suggest features:

### FEATURE_REQUESTS
- <suggestion 1>
- <suggestion 2>
---

Examples:
- "Include full file context for modified functions, not just diff hunks"
- "Show callers of modified methods to verify integration"
- "Include test file alongside implementation changes"

Only include this section if you have specific suggestions. Skip if none.
"""


def build_review_prompt(
    diff_content: str,
    spec_content: str | None = None,
    observations: dict | None = None,
) -> str:
    """
    Build the review prompt with diff, optional spec, and observation results.

    Args:
        diff_content: Git diff to review
        spec_content: Optional spec file content
        observations: Optional dict of observation results from previous iteration

    Returns:
        Complete prompt for model
    """
    import json

    if spec_content:
        spec_section = f"""## Specification

Review the code against this specification. Flag any MUST requirements that are not met.

```markdown
{spec_content}
```
"""
    else:
        spec_section = "## Specification\n\nNo specification provided. Focus on correctness, tests, and integration."

    if observations:
        observations_section = f"""## Observation Results

You previously requested observations. Here are the results:

```json
{json.dumps(observations, indent=2, default=str)}
```

Use these results to inform your review. Do not request the same observations again.
"""
    else:
        observations_section = ""

    return CODE_REVIEW_PROMPT.format(
        spec_section=spec_section,
        diff_content=diff_content,
        observations_section=observations_section,
    )
