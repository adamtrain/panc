import io
import re

import pytest
from rich.console import Console

from panc import render
from panc.client import Result
from panc.render import Kind


def rendered(data: dict, **kwargs) -> str:
    console = Console(record=True, width=100, file=io.StringIO())
    render.report(console, Result.from_api(data), **kwargs)
    return console.export_text()


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Human Written", Kind.HUMAN),
        ("AI-Assisted", Kind.ASSISTED),
        ("AI-Generated", Kind.AI),
        # Wording from older Pangram models.
        ("Unlikely AI", Kind.HUMAN),
        ("Moderately AI-Assisted", Kind.ASSISTED),
        ("Likely AI", Kind.AI),
        ("", Kind.UNKNOWN),
    ],
)
def test_kind_of(label, kind):
    assert render.kind_of(label) is kind


def test_report_shows_verdict_segments_and_notes(mixed):
    out = rendered(mixed)
    assert "MIXED" in out
    assert "AI Detected" in out
    assert "Pangram 4.0 · 4 segments · 176 words" in out
    assert re.search(r"AI-Generated\s+━+\s+98%", out)
    assert "Segment 3 shows signs of an AI humanizer (87%)" in out
    assert "Segment 4 is low-confidence" in out
    # Each paragraph is its own segment, separated by a blank line.
    for n, line in enumerate([1, 3, 5, 7], 1):
        assert re.search(rf"^\s*{n} .* {line}:1 ", out, re.MULTILINE)
    # The full text isn't reproduced.
    assert "It's still there." not in out


def test_brief_only_shows_verdict(mixed):
    out = rendered(mixed, brief=True)
    assert "MIXED" in out
    assert "Segments" not in out


def test_document_map_follows_segment_positions(docs_example):
    bar = render.document_map(Result.from_api(docs_example), 35)
    colors = [str(span.style) for span in bar.spans]
    assisted = render.LOOKS[Kind.ASSISTED].color
    human = render.LOOKS[Kind.HUMAN].color
    # 21 of 35 characters are AI-assisted, the rest human.
    assert colors == [assisted] * 21 + [human] * 14


def test_source_line_fits_on_one_line():
    line = render.source_line("clipboard", "word " * 500, 60)
    assert line.cell_len == 60
    assert line.plain.endswith("…")


@pytest.mark.parametrize(
    ("fixture", "kind", "badge"),
    [("human", Kind.HUMAN, "HUMAN"), ("mixed", Kind.ASSISTED, "MIXED"), ("ai", Kind.AI, "AI")],
)
def test_verdict_badge_and_color(sample, fixture, kind, badge):
    result = Result.from_api(sample(fixture))
    assert render.verdict_kind(result) is kind
    panel = render.verdict_panel(result, 80)
    assert panel.border_style == render.LOOKS[kind].color
    assert f" {badge} " in rendered(sample(fixture), brief=True)
