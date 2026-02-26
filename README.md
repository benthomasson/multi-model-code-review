# multi-model-code-review

AI-first code review using multiple models to surface issues before human review.

## Problem

As AI-assisted development scales, human reviewers become the bottleneck. MRs pile up waiting for human attention while obvious issues could be caught automatically.

## Solution

Run code reviews through multiple AI models (Claude, Gemini, etc.) to:
- Catch issues before human review
- Surface inter-model disagreements as signals for human attention
- Validate implementation against specs
- Provide a CI gate for automated quality control

## Design Principles

Based on [multi-model-review](https://github.com/benthomasson/multi-model-review) for research papers:

1. **Multi-model consensus** - If models disagree, humans should look closer
2. **Structured verdicts** - PASS / CONCERN / BLOCK per change
3. **Spec-aware** - Validate implementation against specifications
4. **CI-ready** - Binary gate (exit 0 = PASS, exit 2 = BLOCK)
5. **Show don't tell** - Check integration, not just interfaces

## Commands

```bash
# Full review with all verdicts
code-review review --spec spec.md --diff branch-name

# Highlight model disagreements
code-review compare --spec spec.md --diff branch-name

# CI gate
code-review gate --spec spec.md --diff branch-name

# Check spec compliance
code-review check-spec --spec spec.md --diff branch-name
```

## Review Dimensions

Each change is assessed on multiple axes:

| Dimension | Verdicts |
|-----------|----------|
| Correctness | VALID / QUESTIONABLE / BROKEN |
| Spec Compliance | MEETS / PARTIAL / VIOLATES |
| Test Coverage | COVERED / PARTIAL / UNTESTED |
| Security | SAFE / REVIEW / VULNERABLE |
| Integration | WIRED / PARTIAL / MISSING |

## Output Example

```
## Review: feat/complexity-router

### src/workflow/complexity_router.py (NEW)
VERDICT: PASS
CORRECTNESS: VALID
SPEC_COMPLIANCE: MEETS
TEST_COVERAGE: COVERED
REASONING: Implementation matches spec. 47 tests cover all methods.

### langflow_components/agentic_planner.py
VERDICT: CONCERN
CORRECTNESS: VALID
INTEGRATION: PARTIAL
REASONING: tier_config param added but not wired to caller.
---

## Model Agreement
- claude: 8P / 1C / 0B
- gemini: 7P / 2C / 0B

## Disagreements
- langflow_components/agentic_planner.py: claude=PASS, gemini=CONCERN

GATE: PASS (no BLOCKs)
```

## Installation

```bash
uv tool install git+https://github.com/benthomasson/multi-model-code-review
```

## Requirements

- `claude` CLI installed and authenticated
- `gemini` CLI installed and authenticated

## Related

- [multi-model-review](https://github.com/benthomasson/multi-model-review) - Paper review (this tool's inspiration)
- [Show, Don't Tell for AI](https://benthomasson.com/ai/collaboration/ftl2/show-dont-tell-ai/) - Design principle

## License

MIT
