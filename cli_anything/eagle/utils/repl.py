from __future__ import annotations

import shlex
from typing import Any

import click


def start_repl(command: click.BaseCommand, base_args: list[str]) -> None:
    click.echo("Eagle REPL. Type 'help' for usage, 'exit' to quit.")
    while True:
        try:
            line = click.prompt("eagle", prompt_suffix="> ", default="", show_default=False).strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        if not line:
            continue
        if line in {"exit", "quit"}:
            break
        if line == "help":
            click.echo("Examples:")
            click.echo("  app info")
            click.echo("  library info")
            click.echo("  folder tree")
            click.echo("  item list --limit 5")
            continue

        try:
            args = [*base_args, *shlex.split(line)]
            command.main(args=args, prog_name="cli-anything-eagle", standalone_mode=False)
        except SystemExit:
            continue
        except Exception as exc:  # pragma: no cover - REPL only
            click.echo(f"error: {exc}")
