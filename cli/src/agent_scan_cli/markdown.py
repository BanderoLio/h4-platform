"""Minimal, zero-dependency markdown-to-ANSI renderer.

The orchestrator returns its report as markdown. Dumping it raw to the
terminal is hard to read, so this module turns the common constructs
(headings, bold, lists, inline/fenced code, rules, quotes) into ANSI-styled
text. It is deliberately small — not a spec-complete parser — and degrades
to clean plain text when colour is disabled.
"""
from __future__ import annotations

import re

from .terminal import BOLD, CYAN, DIM, GREEN, MAGENTA, RESET, YELLOW

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_FENCE = re.compile(r"^\s*```")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")

# Heading colour by depth: H1/H2 stand out, H3+ are just bold.
_HEADING_STYLE = {1: BOLD + MAGENTA, 2: BOLD + CYAN, 3: BOLD + GREEN}


def _paint(text: str, style: str, color: bool) -> str:
    return f"{style}{text}{RESET}" if color else text


def _render_inline(text: str, color: bool) -> str:
    """Apply inline styles: `code` spans first, then **bold**."""
    text = _CODE_SPAN.sub(lambda m: _paint(m.group(1), CYAN, color), text)

    def bold(match: re.Match[str]) -> str:
        return _paint(match.group(1) or match.group(2), BOLD, color)

    return _BOLD.sub(bold, text)


def render_markdown(text: str, *, color: bool = True, rule_width: int = 56) -> str:
    """Render a markdown string into terminal-ready text."""
    lines: list[str] = []
    in_code = False

    for raw in (text or "").splitlines():
        if _FENCE.match(raw):
            in_code = not in_code
            continue

        if in_code:
            lines.append(_paint("  " + raw, DIM, color))
            continue

        heading = _HEADING.match(raw)
        if heading:
            depth = len(heading.group(1))
            style = _HEADING_STYLE.get(depth, BOLD)
            lines.append("")
            lines.append(_paint(_render_inline(heading.group(2), color=False), style, color))
            continue

        if _RULE.match(raw):
            lines.append(_paint("─" * rule_width, DIM, color))
            continue

        quote = _QUOTE.match(raw)
        if quote:
            bar = _paint("│", DIM, color)
            lines.append(f"{bar} {_paint(_render_inline(quote.group(1), color=False), DIM, color)}")
            continue

        bullet = _BULLET.match(raw)
        if bullet:
            indent, body = bullet.group(1), bullet.group(2)
            marker = _paint("•", YELLOW, color)
            lines.append(f"{indent}  {marker} {_render_inline(body, color)}")
            continue

        numbered = _NUMBERED.match(raw)
        if numbered:
            indent, num, body = numbered.groups()
            marker = _paint(f"{num}.", BOLD, color)
            lines.append(f"{indent}  {marker} {_render_inline(body, color)}")
            continue

        lines.append(_render_inline(raw, color))

    return "\n".join(lines)
