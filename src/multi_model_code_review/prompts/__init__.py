"""Review prompts for code review."""

from .review import build_review_prompt
from .spec_check import build_spec_check_prompt

__all__ = [
    "build_review_prompt",
    "build_spec_check_prompt",
]
