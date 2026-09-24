"""Regenerate the README screenshots in docs/.

    uv run scripts/screenshots.py

Each one is rendered from a sample response in tests/fixtures through the same code panc uses
for real results, then saved with rich's SVG export.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

from panc import render
from panc.client import Result

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
DOCS = ROOT / "docs"
PROMPT = "\u276f "  # a shell-prompt chevron

THEME = TerminalTheme(
    background=(16, 18, 25),
    foreground=(226, 228, 236),
    normal=[
        (32, 34, 44),
        (242, 80, 110),
        (31, 191, 143),
        (235, 154, 18),
        (124, 131, 247),
        (168, 113, 247),
        (86, 182, 194),
        (200, 202, 212),
    ],
    bright=[
        (92, 96, 112),
        (255, 110, 136),
        (70, 214, 170),
        (250, 184, 60),
        (152, 158, 255),
        (190, 146, 255),
        (120, 208, 220),
        (255, 255, 255),
    ],
)


def terminal(width: int) -> Console:
    return Console(
        record=True,
        width=width,
        force_terminal=True,
        color_system="truecolor",
        highlight=False,
        file=io.StringIO(),
    )


def session(console: Console, command: str, fixture: str, origin: str, **options) -> None:
    """Draw what running `command` on a fixture's text looks like."""
    data = json.loads((FIXTURES / f"{fixture}.json").read_text())
    console.print(Text.assemble((PROMPT, f"bold {render.ACCENT}"), (command, "bold")))
    console.print(render.source_line(origin, data["text"], console.width))
    render.report(console, Result.from_api(data), original=data["text"], **options)


def main() -> None:
    DOCS.mkdir(exist_ok=True)

    hero = terminal(100)
    session(hero, "panc", "mixed", "clipboard")
    hero.save_svg(str(DOCS / "hero.svg"), title="panc", theme=THEME)

    verdicts = terminal(76)
    session(verdicts, "pbpaste | panc --brief", "human", "stdin", brief=True)
    verdicts.print()
    verdicts.print()
    session(verdicts, "panc -b -f memo.md", "ai", "memo.md", brief=True)
    verdicts.print()
    verdicts.save_svg(str(DOCS / "verdicts.svg"), title="panc --brief", theme=THEME)

    for path in sorted(DOCS.glob("*.svg")):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
