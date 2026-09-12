#!/usr/bin/env python3
"""Small, dependency-free checks for documentation that has become hard to read.

This is deliberately not a grammar checker. Technical prose sometimes needs a
long sentence, passive voice, or repeated terminology. The checks below only
point out passages worth rereading.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]

MAX_PARAGRAPH_WORDS = 170
MAX_SENTENCE_WORDS = 55
REPEATED_OPENERS = (
    "what that does not",
    "what it cannot",
    "nothing here says",
    "that is the honest answer",
    "be clear about",
    "be precise about",
)


def prose_blocks(text: str):
    """Yield prose paragraphs, skipping fenced code and Markdown tables."""
    in_fence = False
    block = []
    start = 1
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            if block:
                yield start, " ".join(block)
                block = []
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith("|"):
            continue
        if not line.strip():
            if block:
                yield start, " ".join(block)
                block = []
            continue
        if not block:
            start = lineno
        block.append(line.strip())
    if block:
        yield start, " ".join(block)


def check(path: Path):
    text = path.read_text(encoding="utf-8")
    warnings = []
    opener_counts = {phrase: len(re.findall(re.escape(phrase), text.lower()))
                     for phrase in REPEATED_OPENERS}
    for phrase, count in opener_counts.items():
        if count > 2:
            warnings.append((1, f"phrase '{phrase}' appears {count} times"))

    for lineno, paragraph in prose_blocks(text):
        words = paragraph.split()
        if len(words) > MAX_PARAGRAPH_WORDS:
            warnings.append((lineno, f"long paragraph: {len(words)} words"))
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            count = len(sentence.split())
            if count > MAX_SENTENCE_WORDS:
                warnings.append((lineno, f"long sentence: about {count} words"))
    return warnings


def main() -> int:
    total = 0
    for path in DOCS:
        for lineno, message in check(path):
            total += 1
            print(f"{path.relative_to(ROOT)}:{lineno}: {message}")
    if total:
        print(f"\n{total} documentation warning(s). Reread them; exceptions are fine.")
    else:
        print("Documentation checks passed.")
    # Advisory by design: this should never make a good technical sentence fail CI.
    return 0


if __name__ == "__main__":
    sys.exit(main())
