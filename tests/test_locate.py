from itertools import pairwise

from panc.client import Result
from panc.locate import line_col, segment_starts


def result_for(returned: str, cuts: list[int]) -> Result:
    """A result whose windows split `returned` at the given offsets."""
    bounds = [0, *cuts, len(returned)]
    windows = [
        {"text": returned[a:b], "label": "Human Written", "start_index": a, "end_index": b}
        for a, b in pairwise(bounds)
    ]
    return Result.from_api({"text": returned, "windows": windows})


def test_exact_text_uses_pangram_offsets_shifted_into_the_original():
    returned = "First part.\n\nSecond part."
    original = "  \n" + returned + "\n"
    starts = segment_starts(original, result_for(returned, [11]))
    # The second window begins with "\n\n", so it's reported at the "S" after them.
    assert [original[s] for s in starts] == ["F", "S"]
    assert [line_col(original, s) for s in starts] == [(2, 1), (4, 1)]


def test_normalized_text_is_found_by_its_opening_words():
    original = "He said “hello”  there.\r\n\r\nThen—quietly—left."
    returned = 'He said "hello" there.\n\nThen-quietly-left.'
    starts = segment_starts(original, result_for(returned, [22]))
    assert starts == [0, original.index("Then")]
    assert line_col(original, starts[1]) == (3, 1)


def test_unfindable_segments_are_none():
    starts = segment_starts("Nothing alike.", result_for("Totally different", [8]))
    assert starts == [None, None]


def test_line_col():
    text = "ab\ncd\n\nef"
    assert line_col(text, 0) == (1, 1)
    assert line_col(text, 4) == (2, 2)
    assert line_col(text, text.index("e")) == (4, 1)
