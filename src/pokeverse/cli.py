"""Command-line interface for PokéVerse AI."""

from importlib.metadata import version
from typing import Annotated

import typer

app = typer.Typer(add_completion=False, no_args_is_help=False)


@app.callback(invoke_without_command=True)
def main(
    version_flag: Annotated[
        bool,
        typer.Option("--version", help="Show the installed PokéVerse AI version."),
    ] = False,
) -> None:
    if version_flag:
        typer.echo(version("pokeverse-ai"))
        raise typer.Exit

    typer.echo("Welcome to PokéVerse AI")


def run() -> None:
    app()
