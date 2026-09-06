"""Shared text-formatting helpers for projector implementations.

Not a projector itself -- factored out because every provider needs the
same "render an optional field as a line, drop it if empty" logic, and
`base.py` must stay a pure interface (see `.claude/rules/coding-patterns.md`).
"""

from __future__ import annotations

from typing import Any


def field_line(label: str, value: Any) -> str | None:
    """Render `"Label: value"`, or `None` if `value` is empty/falsy."""
    if value is None or value == "" or value == []:
        return None
    return f"{label}: {value}"


def join_lines(*lines: str | None) -> str:
    """Join non-empty lines into one block of text."""
    return "\n".join(line for line in lines if line)
