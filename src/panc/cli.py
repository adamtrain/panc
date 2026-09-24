"""`panc`: ask Pangram whether some text was written by AI."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Annotated, TextIO

import typer
from rich.console import Console

from . import __version__, render
from .client import DEFAULT_MODEL, Pangram, PangramError
from .clipboard import ClipboardError, read_clipboard

ENV_KEY = "PANGRAM_API_KEY"

out = Console(highlight=False)
err = Console(stderr=True, highlight=False)

app = typer.Typer(
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


class InputError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def _stdin_is_piped(stdin: TextIO) -> bool:
    """True when stdin is a pipe or redirected file, not a terminal or /dev/null."""
    try:
        mode = os.fstat(stdin.fileno()).st_mode
    except (OSError, ValueError, AttributeError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode) or stat.S_ISSOCK(mode)


def _read(stdin: TextIO) -> str:
    buffer = getattr(stdin, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", errors="replace")
    return stdin.read()


def resolve_input(
    words: list[str] | None, file: Path | None, stdin: TextIO | None = None
) -> tuple[str, str]:
    """Work out what to analyze: a file, arguments, piped stdin, or else the clipboard.

    Returns (text, origin) where origin is a short description for display.
    """
    stdin = stdin or sys.stdin
    if file is not None:
        if str(file) == "-":
            return _read(stdin), "stdin"
        try:
            return file.read_text(encoding="utf-8", errors="replace"), file.name
        except OSError as e:
            raise InputError(f"Couldn't read {file}: {e.strerror or e}") from e
    if words:
        if words == ["-"]:
            return _read(stdin), "stdin"
        return " ".join(words), "argument"
    if _stdin_is_piped(stdin):
        return _read(stdin), "stdin"
    try:
        return read_clipboard(), "clipboard"
    except ClipboardError as e:
        raise InputError(
            str(e), hint='Pipe text in or pass it as an argument instead: [bold]panc "…"[/]'
        ) from e


EMPTY_HINTS = {
    "clipboard": (
        "Your clipboard is empty.",
        "Copy some text first, pipe it in ([bold]cat essay.txt | panc[/]), "
        'or pass it directly ([bold]panc "…"[/]).',
    ),
    "stdin": ("Nothing came through stdin.", None),
    "argument": ("That argument is blank.", None),
}


def _version(value: bool) -> None:
    if value:
        out.print(f"panc {__version__}")
        raise typer.Exit()


def _api_key() -> str:
    key = os.environ.get(ENV_KEY, "").strip()
    if not key:
        render.error(
            err,
            f"{ENV_KEY} isn't set.",
            hint=(
                "Create an API key in your Pangram account (https://www.pangram.com), then:\n"
                f"  [bold]export {ENV_KEY}=[/][dim]your-key[/]"
            ),
        )
        raise typer.Exit(1)
    return key


EPILOG = (
    "[bold]Examples[/]\n\n"
    "  [cyan]panc[/]                       analyze whatever is on your clipboard\n"
    "  [cyan]pbpaste | panc[/]             …or pipe it in\n"
    '  [cyan]panc "Some prose here"[/]     …or pass it directly\n'
    "  [cyan]panc -f essay.md --json[/]    …read a file, print raw JSON\n\n"
    f"Reads your API key from [bold]${ENV_KEY}[/]."
)


@app.command(epilog=EPILOG)
def run(
    text: Annotated[
        list[str] | None,
        typer.Argument(
            help="Text to analyze (words are joined with spaces). Use [bold]-[/] for stdin.",
            show_default=False,
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read the text from a file.", show_default=False),
    ] = None,
    brief: Annotated[bool, typer.Option("--brief", "-b", help="Only show the verdict.")] = False,
    link: Annotated[
        bool, typer.Option("--link", "-l", help="Ask Pangram for a shareable dashboard link.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", "-j", help="Print Pangram's raw response as JSON.")
    ] = False,
    model: Annotated[
        str, typer.Option("--model", "-m", help="Model selector to use (see --list-models).")
    ] = DEFAULT_MODEL,
    list_models: Annotated[
        bool, typer.Option("--list-models", help="List the models your API key can use.")
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option("--version", "-V", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Check whether text was written by AI, using [bold]Pangram[/].

    With no input, [bold]panc[/] reads your clipboard. Pipe text in or pass it
    as an argument to analyze that instead.
    """
    key = _api_key()
    client = Pangram(key, user_agent=f"panc/{__version__}")
    try:
        if list_models:
            with err.status(render.stage_message("STAGE_LISTING_MODELS"), spinner_style="dim"):
                models = client.list_models()
            render.model_list(out, models, model)
            return

        try:
            content, origin = resolve_input(text, file)
        except InputError as e:
            render.error(err, str(e), hint=e.hint)
            raise typer.Exit(1) from e
        if not content.strip():
            message, hint = EMPTY_HINTS.get(origin, (f"{origin} is empty.", None))
            render.error(err, message, hint=hint)
            raise typer.Exit(1)
        original, content = content, content.strip()

        if not as_json:
            err.print(render.source_line(origin, content, err.width))
        with err.status(render.stage_message(""), spinner_style=render.ACCENT) as status:
            result = client.detect(
                content,
                model=model,
                dashboard_link=link,
                on_stage=lambda stage: status.update(render.stage_message(stage)),
            )
    except PangramError as e:
        hint = f"Check [bold]${ENV_KEY}[/]." if e.status == 401 else None
        if e.status in (403, 422):
            hint = "See which models your key can use with [bold]panc --list-models[/]."
        render.error(err, str(e), detail=e.detail, hint=hint)
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        err.print("[dim]Cancelled.[/]")
        raise typer.Exit(130) from None
    finally:
        client.close()

    if as_json and out.is_terminal:
        out.print_json(data=result.raw)
    elif as_json:
        print(json.dumps(result.raw, indent=2, ensure_ascii=False))
    else:
        render.report(out, result, original=original, brief=brief)


def main() -> None:
    app()
