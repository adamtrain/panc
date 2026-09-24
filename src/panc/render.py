"""Turn Pangram results into something pleasant to read in a terminal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .client import Result, Window
from .locate import line_col, segment_starts

MAX_WIDTH = 120

ACCENT = "#7c83f7"
HUMANIZED = "#a871f7"
ERROR = "#f2506e"
FAINT = "grey42"


class Kind(StrEnum):
    HUMAN = "human"
    ASSISTED = "assisted"
    AI = "ai"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Look:
    name: str
    color: str


LOOKS = {
    Kind.HUMAN: Look("Human", "#1fbf8f"),
    Kind.ASSISTED: Look("AI-assisted", "#eb9a12"),
    Kind.AI: Look("AI-generated", "#f2506e"),
    Kind.UNKNOWN: Look("Unclassified", FAINT),
}

CONFIDENCE_DOTS = {"high": 3, "medium": 2, "low": 1}


def kind_of(label: str) -> Kind:
    """Bucket a window label (current or legacy wording) into one of three kinds."""
    words = re.findall(r"[a-z]+", label.lower())
    if "human" in words or "unlikely" in words:
        return Kind.HUMAN
    if any(w.startswith("assist") for w in words) or "mixed" in words:
        return Kind.ASSISTED
    if "ai" in words:
        return Kind.AI
    return Kind.UNKNOWN


def verdict_kind(result: Result) -> Kind:
    match result.prediction_short.strip().lower():
        case "ai":
            return Kind.AI
        case "human":
            return Kind.HUMAN
        case "mixed":
            return Kind.ASSISTED
    return kind_of(result.headline)


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _width(console: Console) -> int:
    return min(console.width, MAX_WIDTH)


# ── Pieces ────────────────────────────────────────────────────────────────────


def document_map(result: Result, width: int) -> Text:
    """A bar where each cell is colored by whatever Pangram said about that stretch of text."""
    total = len(result.text) or max((w.end_index for w in result.windows), default=0)
    bar = Text(no_wrap=True)
    if not total or not result.windows:
        return bar.append("━" * width, style=FAINT)
    for i in range(width):
        pos = (i + 0.5) * total / width
        covering = [w for w in result.windows if w.start_index <= pos < w.end_index]
        # Windows can overlap; the most AI-ish reading of a spot wins.
        window = max(covering, key=lambda w: w.ai_assistance_score, default=None)
        kind = kind_of(window.label) if window else Kind.UNKNOWN
        bar.append("━", style=LOOKS[kind].color)
    return bar


def legend(result: Result) -> Text:
    shares = [
        (Kind.HUMAN, result.fraction_human),
        (Kind.ASSISTED, result.fraction_ai_assisted),
        (Kind.AI, result.fraction_ai),
    ]
    text = Text()
    for i, (kind, share) in enumerate(shares):
        look = LOOKS[kind]
        present = share > 0
        if i:
            text.append("     ")
        text.append("● ", style=look.color if present else FAINT)
        text.append(f"{look.name} ", style="" if present else FAINT)
        text.append(f"{share:.0%}", style=f"bold {look.color}" if present else FAINT)
    return text


def verdict_panel(result: Result, width: int) -> Panel:
    kind = verdict_kind(result)
    color = LOOKS[kind].color
    badge = (result.prediction_short or LOOKS[kind].name).upper()
    heading = Text.assemble(
        (f" {badge} ", f"bold #111111 on {color}"),
        "  ",
        (result.headline, f"bold {color}"),
    )
    meta = " · ".join(
        part
        for part in (
            f"Pangram {result.version}" if result.version else "",
            _plural(len(result.windows), "segment"),
            _plural(result.word_count, "word"),
        )
        if part
    )
    body = Group(
        heading,
        Text(),
        Text(result.prediction),
        Text(),
        document_map(result, width - 6),
        legend(result),
    )
    return Panel(
        body,
        box=box.ROUNDED,
        border_style=color,
        padding=(1, 2),
        subtitle=Text(f" {meta} ", style=FAINT),
        subtitle_align="right",
        width=width,
    )


def score_bar(score: float, color: str, cells: int = 10) -> Text:
    filled = round(max(0.0, min(score, 1.0)) * cells)
    return Text.assemble(
        ("━" * filled, color),
        ("─" * (cells - filled), FAINT),
        (f" {score:>4.0%}", "bold" if filled else FAINT),
    )


def confidence_dots(confidence: str) -> Text:
    n = CONFIDENCE_DOTS.get(confidence.lower(), 0)
    return Text.assemble(("●" * n, ""), ("○" * (3 - n), FAINT), (f" {confidence.lower()}", FAINT))


def segment_label(window: Window) -> Text:
    look = LOOKS[kind_of(window.label)]
    text = Text.assemble(("● ", look.color), (window.label or look.name, look.color))
    if window.is_humanized:
        text.append(" ⚑", style=HUMANIZED)
    return text


def segments_table(result: Result, original: str, width: int) -> Table:
    """One row per segment, ending with where it starts in the original input."""
    table = Table(box=None, pad_edge=False, padding=(0, 1), header_style=FAINT, width=width)
    table.add_column("#", justify="right", style=FAINT, no_wrap=True)
    table.add_column("Segment", no_wrap=True)
    table.add_column("AI score", no_wrap=True)
    table.add_column("Confidence", no_wrap=True)
    table.add_column("Words", justify="right", no_wrap=True)
    table.add_column("Ln:Col", no_wrap=True)
    table.add_column("Starts with", ratio=1, no_wrap=True, overflow="ellipsis", style="italic")
    starts = segment_starts(original, result)
    for i, (window, start) in enumerate(zip(result.windows, starts, strict=True), 1):
        color = LOOKS[kind_of(window.label)].color
        if start is None:
            where = Text("?", style=FAINT)
        else:
            line, col = line_col(original, start)
            where = Text.assemble(str(line), (f":{col}", FAINT))
        table.add_row(
            str(i),
            segment_label(window),
            score_bar(window.ai_assistance_score, color),
            confidence_dots(window.confidence),
            f"{window.word_count:,}",
            where,
            " ".join(window.text.split()),
        )
    return table


def _join_numbers(numbers: list[int]) -> str:
    if len(numbers) == 1:
        return str(numbers[0])
    return ", ".join(map(str, numbers[:-1])) + f" and {numbers[-1]}"


def notes(result: Result) -> Table | None:
    """Footnotes worth calling out beneath the segment table."""
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True)
    grid.add_column()
    humanized = [(i, w) for i, w in enumerate(result.windows, 1) if w.is_humanized]
    if humanized:
        which = _join_numbers([i for i, _ in humanized])
        scores = [w.humanizer_score for _, w in humanized if w.humanizer_score is not None]
        strength = f" ({'up to ' if len(scores) > 1 else ''}{max(scores):.0%})" if scores else ""
        one = len(humanized) == 1
        grid.add_row(
            Text("⚑", style=HUMANIZED),
            Text.assemble(
                (f"{'Segment' if one else 'Segments'} {which}", "bold"),
                f" {'shows' if one else 'show'} signs of an AI humanizer{strength}: "
                "machine-paraphrased text made to slip past detectors.",
            ),
        )
    low = [i for i, w in enumerate(result.windows, 1) if w.confidence.lower() == "low"]
    if low:
        one = len(low) == 1
        grid.add_row(
            Text("○", style=FAINT),
            Text.assemble(
                (f"{'Segment' if one else 'Segments'} {_join_numbers(low)}", "bold"),
                f" {'is' if one else 'are'} low-confidence. "
                f"Treat {'it' if one else 'them'} with caution.",
            ),
        )
    return grid if grid.row_count else None


def _section(title: str, width: int) -> Rule:
    return Rule(Text(f" {title} ", style=FAINT), align="left", style=FAINT, characters="─")


# ── Top-level views ───────────────────────────────────────────────────────────


def report(console: Console, result: Result, *, original: str | None = None, brief: bool = False):
    """Print the verdict and segment breakdown.

    `original` is the text as the user supplied it, so segment positions refer to their input.
    """
    width = _width(console)
    console.print()
    console.print(verdict_panel(result, width))
    if brief:
        _dashboard(console, result)
        return

    if result.windows:
        console.print()
        console.print(_section("Segments", width), width=width)
        console.print(segments_table(result, original or result.text, width))
        if footnotes := notes(result):
            console.print()
            console.print(footnotes, width=width)

    _dashboard(console, result)
    console.print()


def _dashboard(console: Console, result: Result) -> None:
    if result.dashboard_link:
        console.print()
        link = Text(result.dashboard_link, style=f"underline {ACCENT} link {result.dashboard_link}")
        console.print(Text.assemble(("↗ ", ACCENT), "Full report: ", link))


def source_line(origin: str, text: str, width: int) -> Text:
    words = len(text.split())
    preview = " ".join(text.split())
    line = Text()
    line.append("◇ ", style=ACCENT)
    line.append(origin, style=f"bold {ACCENT}")
    line.append(f" · {_plural(words, 'word')} · ", style=FAINT)
    line.append(f"“{preview}”", style=f"italic {FAINT}")
    line.truncate(width, overflow="ellipsis")
    return line


def stage_message(stage: str) -> Text:
    step = stage.removeprefix("STAGE_").replace("_", " ").lower() or "submitting"
    return Text.assemble(("Asking Pangram", ACCENT), (f" · {step}", FAINT))


def error(console: Console, message: str, *, detail: str | None = None, hint: str | None = None):
    console.print(Text.assemble(("✗ ", f"bold {ERROR}"), (message, "bold")))
    if detail:
        console.print(Text(f"  {detail}", style=FAINT))
    if hint:
        console.print(Text.from_markup(f"  {hint}"))


def model_list(console: Console, models: list[str], current: str) -> None:
    console.print()
    for name in models:
        chosen = name == current
        console.print(
            Text.assemble(
                ("● " if chosen else "○ ", ACCENT if chosen else FAINT),
                (name, "bold" if chosen else ""),
                ("  (selected)" if chosen else "", FAINT),
            )
        )
    console.print()
