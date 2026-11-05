"""Command-line interface for PokéVerse AI."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from dotenv import find_dotenv, load_dotenv

from pokeverse.catalog import (
    Pokemon,
    PokemonCatalog,
    PokemonNotInCatalogError,
    SqlitePokemonRepository,
    UpstreamUnavailableError,
)
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.llm import (
    LlmAuthError,
    LlmRequestError,
    LlmSettings,
    LlmUnavailableError,
    OpenAIChat,
)

EXIT_NOT_FOUND = 1
EXIT_INVALID_INPUT = 2
EXIT_UPSTREAM_UNAVAILABLE = 3
EXIT_AUTH = 4

DEFAULT_SYSTEM_PROMPT = (
    "You are the PokéVerse AI assistant, an expert on Pokémon games and battle mechanics. "
    "Answer concisely. If you are not sure about a fact, say so instead of guessing."
)

app = typer.Typer(add_completion=False, no_args_is_help=False)


def default_db_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "pokeverse" / "catalog.db"


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_flag: Annotated[
        bool,
        typer.Option("--version", help="Show the installed PokéVerse AI version."),
    ] = False,
    db: Annotated[
        Path | None,
        typer.Option(
            "--db",
            envvar="POKEVERSE_DB",
            help="Local catalog database. [default: ~/.local/share/pokeverse/catalog.db]",
            dir_okay=False,
        ),
    ] = None,
) -> None:
    if version_flag:
        typer.echo(version("pokeverse-ai"))
        raise typer.Exit

    ctx.obj = Settings(db_path=db or default_db_path())

    if ctx.invoked_subcommand is None:
        typer.echo("Welcome to PokéVerse AI")


@contextmanager
def open_catalog(settings: Settings, *, offline: bool) -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(settings.db_path) as repository:
        if offline:
            yield PokemonCatalog(repository)
            return
        with PokeApiClient() as client:
            yield PokemonCatalog(repository, client)


def parse_cli_identifier(raw: str) -> str | int:
    stripped = raw.strip()
    return int(stripped) if stripped.isdigit() else stripped


def format_pokemon(pokemon: Pokemon) -> str:
    types = " / ".join(pokemon_type.value.title() for pokemon_type in pokemon.types)
    return f"#{pokemon.pokedex_id:04d} {pokemon.display_name} — {types}"


def fail(message: str, code: int) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code)


@app.command("pokemon")
def pokemon_command(
    ctx: typer.Context,
    name_or_id: Annotated[str, typer.Argument(help="Pokémon name (e.g. pikachu) or Pokédex id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Only use the local catalog; never call PokéAPI.")
    ] = False,
) -> None:
    """Look up a Pokémon, importing it from PokéAPI if not stored locally."""
    settings: Settings = ctx.obj
    try:
        identifier = parse_cli_identifier(name_or_id)
        with open_catalog(settings, offline=offline) as catalog:
            pokemon = catalog.get(identifier)
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except PokemonNotInCatalogError as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    typer.echo(json.dumps(pokemon.to_dict()) if as_json else format_pokemon(pokemon))


@app.command("list")
def list_command(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """List Pokémon stored in the local catalog (no network access)."""
    settings: Settings = ctx.obj
    with open_catalog(settings, offline=True) as catalog:
        stored = catalog.list_all()

    if as_json:
        typer.echo(json.dumps([pokemon.to_dict() for pokemon in stored]))
    elif not stored:
        typer.echo("The local catalog is empty. Try: pokeverse pokemon pikachu")
    else:
        for pokemon in stored:
            typer.echo(format_pokemon(pokemon))


@app.command("ask")
def ask_command(
    question: Annotated[str, typer.Argument(help="Question or prompt for the model.")],
    system: Annotated[
        str, typer.Option("--system", help="System prompt (sets the model's role and rules).")
    ] = DEFAULT_SYSTEM_PROMPT,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", "-t", min=0.0, max=1.0, help="Sampling randomness 0.0-1.0."),
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", min=1, help="Maximum tokens in the reply.")
    ] = None,
    show_usage: Annotated[
        bool, typer.Option("--usage", help="Print model, token usage and latency to stderr.")
    ] = False,
) -> None:
    """Ask the LLM a question directly (no tools, no catalog data yet)."""
    try:
        chat = OpenAIChat(LlmSettings.from_env())
        completion = chat.complete(
            question, system=system or None, temperature=temperature, max_tokens=max_tokens
        )
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except LlmAuthError as error:
        raise fail(str(error), EXIT_AUTH) from error
    except LlmUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error
    except LlmRequestError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error

    typer.echo(completion.text)
    if show_usage:
        typer.echo(
            f"[{completion.model_id}] tokens in={completion.input_tokens} "
            f"out={completion.output_tokens} total={completion.total_tokens} "
            f"stop={completion.stop_reason} latency={completion.latency_ms}ms",
            err=True,
        )


def run() -> None:
    # Real environment variables take precedence over .env values.
    load_dotenv(find_dotenv(usecwd=True))
    app()
