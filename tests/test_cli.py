import io
import json
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from panc import cli
from panc.client import Result
from panc.clipboard import ClipboardError

runner = CliRunner()


class FakeStdin(io.StringIO):
    """A stdin stand-in that looks like a pipe (or not)."""

    def __init__(self, text: str, piped: bool):
        super().__init__(text)
        self.piped = piped


@pytest.fixture(autouse=True)
def fake_pipe_detection(monkeypatch):
    monkeypatch.setattr(cli, "_stdin_is_piped", lambda stdin: getattr(stdin, "piped", False))


@pytest.fixture
def clipboard(monkeypatch):
    contents = {"text": "from the clipboard"}
    monkeypatch.setattr(cli, "read_clipboard", lambda: contents["text"])
    return contents


def test_arguments_are_joined(clipboard):
    assert cli.resolve_input(["hello", "world"], None) == ("hello world", "argument")


def test_dash_reads_stdin(clipboard):
    stdin = FakeStdin("piped text", piped=False)
    assert cli.resolve_input(["-"], None, stdin) == ("piped text", "stdin")


def test_piped_stdin_beats_clipboard(clipboard):
    stdin = FakeStdin("piped text", piped=True)
    assert cli.resolve_input(None, None, stdin) == ("piped text", "stdin")


def test_clipboard_is_the_default(clipboard):
    stdin = FakeStdin("", piped=False)
    assert cli.resolve_input(None, None, stdin) == ("from the clipboard", "clipboard")


def test_file_option(tmp_path, clipboard):
    essay = tmp_path / "essay.md"
    essay.write_text("an essay")
    assert cli.resolve_input(["ignored"], essay) == ("an essay", "essay.md")


def test_missing_clipboard_tool_explains_alternatives(monkeypatch):
    def broken():
        raise ClipboardError("No clipboard tool found")

    monkeypatch.setattr(cli, "read_clipboard", broken)
    with pytest.raises(cli.InputError) as e:
        cli.resolve_input(None, None, FakeStdin("", piped=False))
    assert "argument" in e.value.hint


# ── End to end, with Pangram faked out ────────────────────────────────────────


class FakePangram:
    calls: ClassVar[list[dict]] = []
    response: ClassVar[dict] = {}

    def __init__(self, api_key, **kwargs):
        self.api_key = api_key

    def detect(self, text, **kwargs):
        FakePangram.calls.append({"text": text, **kwargs})
        kwargs["on_stage"]("STAGE_SUCCESS")
        return Result.from_api(FakePangram.response)

    def list_models(self):
        return ["default", "pangram-4"]

    def close(self):
        pass


@pytest.fixture
def pangram(monkeypatch, mixed):
    FakePangram.calls = []
    FakePangram.response = mixed
    monkeypatch.setattr(cli, "Pangram", FakePangram)
    monkeypatch.setenv(cli.ENV_KEY, "secret")
    return FakePangram


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv(cli.ENV_KEY, raising=False)
    result = runner.invoke(cli.app, ["hello"])
    assert result.exit_code == 1
    assert "PANGRAM_API_KEY isn't set" in result.output


def test_empty_clipboard(pangram, clipboard):
    clipboard["text"] = "  \n"
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 1
    assert "clipboard is empty" in result.output
    assert pangram.calls == []


def test_report_for_argument(pangram):
    result = runner.invoke(cli.app, ["Some", "prose", "--model", "pangram-4", "--link"])
    assert result.exit_code == 0, result.output
    assert pangram.calls[0]["text"] == "Some prose"
    assert pangram.calls[0]["model"] == "pangram-4"
    assert pangram.calls[0]["dashboard_link"] is True
    assert "argument · 2 words" in result.output
    assert "AI Detected" in result.output


def test_pangram_4_is_the_default_model(pangram):
    runner.invoke(cli.app, ["Some", "prose"])
    assert pangram.calls[0]["model"] == "pangram-4"


def test_positions_refer_to_the_untrimmed_input(pangram, mixed):
    # Two leading blank lines get trimmed before sending; positions should still count them.
    result = runner.invoke(cli.app, ["-"], input="\n\n" + mixed["text"] + "\n")
    assert result.exit_code == 0, result.output
    assert " 3:1 " in result.output
    assert " 9:1 " in result.output


def test_json_output_is_the_raw_response(pangram, mixed):
    result = runner.invoke(cli.app, ["--json", "-"], input="  piped in  \n")
    assert result.exit_code == 0, result.output
    assert pangram.calls[0]["text"] == "piped in"
    assert json.loads(result.stdout) == mixed


def test_list_models(pangram):
    result = runner.invoke(cli.app, ["--list-models"])
    assert result.exit_code == 0
    assert "pangram-4  (selected)" in result.output
