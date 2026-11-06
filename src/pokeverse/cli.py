"""Command-line interface for PokéVerse AI."""

import json
import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from dotenv import find_dotenv, load_dotenv

from pokeverse.agents import (
    POKEDEX_ANSWER_SCHEMA,
    PokedexAnswer,
    ResearchAgent,
    make_catalog_tools,
    normalize_pokemon_identifier,
)
from pokeverse.catalog import (
    Pokemon,
    PokemonCatalog,
    PokemonNotInCatalogError,
    SqlitePokemonRepository,
    UpstreamUnavailableError,
)
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.evals import RESEARCH_CASES, EvalResult, run_case
from pokeverse.llm import (
    Completion,
    LlmAuthError,
    LlmRequestError,
    LlmSettings,
    LlmUnavailableError,
    OpenAIChat,
)
from pokeverse.teams import MAX_TEAM_SIZE, Team, analyze_team

EXIT_NOT_FOUND = 1
EXIT_INVALID_INPUT = 2
EXIT_UPSTREAM_UNAVAILABLE = 3
EXIT_AUTH = 4
EXIT_EVAL_FAILED = 5

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


@app.command("team")
def team_command(
    ctx: typer.Context,
    names: Annotated[
        list[str], typer.Argument(help="1-6 Pokémon names or Pokédex ids (repeats allowed).")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Only use the local catalog; never call PokéAPI.")
    ] = False,
) -> None:
    """Analyze a team's type weaknesses and coverage (deterministic, no LLM)."""
    settings: Settings = ctx.obj
    if len(names) > MAX_TEAM_SIZE:
        raise fail(f"a team can have at most {MAX_TEAM_SIZE} Pokémon", EXIT_INVALID_INPUT)
    try:
        with open_catalog(settings, offline=offline) as catalog:
            members = tuple(catalog.get(normalize_pokemon_identifier(name)) for name in names)
        analysis = analyze_team(Team(members))
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except PokemonNotInCatalogError as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    if as_json:
        typer.echo(json.dumps(analysis.to_dict()))
        return
    typer.echo("Team: " + ", ".join(member.display_name for member in analysis.team.members))
    typer.echo("Vulnerable to:" + ("" if analysis.vulnerabilities else " none"))
    for exposure in analysis.vulnerabilities:
        cover = ", ".join(exposure.resists + exposure.immune) or "nobody"
        weak = ", ".join(exposure.weak)
        typer.echo(f"  {exposure.attacking_type:<9} weak: {weak} | resisted by: {cover}")
    typer.echo("Unresisted attack types: " + (", ".join(analysis.unresisted) or "none"))
    typer.echo("Offensive gaps (STAB): " + (", ".join(analysis.offensive_gaps) or "none"))


@app.command("ask")
def ask_command(
    ctx: typer.Context,
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
    use_tools: Annotated[
        bool,
        typer.Option("--tools/--no-tools", help="Let the model look up Pokémon in the catalog."),
    ] = True,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print a validated, structured answer as JSON.")
    ] = False,
) -> None:
    """Ask the LLM a question, letting it look up Pokémon in the local catalog."""
    settings: Settings = ctx.obj
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with ExitStack() as stack:
            tools = ()
            if use_tools:
                catalog = stack.enter_context(open_catalog(settings, offline=False))
                tools = make_catalog_tools(catalog)
            completion = chat.complete(
                question,
                system=system or None,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                output_schema=POKEDEX_ANSWER_SCHEMA if as_json else None,
            )
        if as_json:
            try:
                answer = PokedexAnswer.from_dict(completion.data or {})
            except ValueError as error:
                raise LlmRequestError(f"Model reply failed validation: {error}") from error

    typer.echo(json.dumps(answer.to_dict()) if as_json else completion.text)
    if show_usage:
        print_usage(completion)


@contextmanager
def llm_errors() -> Iterator[None]:
    """Map LLM and input errors to exit codes, with the message on stderr."""
    try:
        yield
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except LlmAuthError as error:
        raise fail(str(error), EXIT_AUTH) from error
    except LlmUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error
    except LlmRequestError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error


def print_usage(completion: Completion) -> None:
    for call in completion.tool_calls:
        typer.echo(
            f"[tool] {call.name}({json.dumps(call.arguments)}) -> {json.dumps(call.output)}",
            err=True,
        )
    typer.echo(
        f"[{completion.model_id}] tokens in={completion.input_tokens} "
        f"out={completion.output_tokens} total={completion.total_tokens} "
        f"stop={completion.stop_reason} latency={completion.latency_ms}ms",
        err=True,
    )


@app.command("research")
def research_command(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Question about one or more Pokémon.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
    show_usage: Annotated[
        bool, typer.Option("--usage", help="Print tool calls and token usage to stderr.")
    ] = False,
) -> None:
    """Ask the Pokémon Research Agent; answers are grounded in the local catalog."""
    settings: Settings = ctx.obj
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with open_catalog(settings, offline=False) as catalog:
            result = ResearchAgent(chat, catalog).ask(question)

    if as_json:
        typer.echo(json.dumps(result.to_dict()))
    else:
        typer.echo(result.answer.answer)
        typer.echo(f"(confidence: {result.answer.confidence})", err=True)
    if result.ungrounded:
        typer.echo(
            f"Warning: not verified against the catalog: {', '.join(result.ungrounded)}",
            err=True,
        )
    if show_usage:
        print_usage(result.completion)


@app.command("eval")
def eval_command(
    ctx: typer.Context,
    case_ids: Annotated[
        list[str] | None,
        typer.Option("--case", help="Run only this case id (repeatable)."),
    ] = None,
) -> None:
    """Run the Research Agent evaluation suite (live model calls; costs tokens)."""
    settings: Settings = ctx.obj
    cases = RESEARCH_CASES
    if case_ids:
        known = {case.id: case for case in RESEARCH_CASES}
        unknown = [case_id for case_id in case_ids if case_id not in known]
        if unknown:
            raise fail(f"unknown case(s) {unknown}; known: {sorted(known)}", EXIT_INVALID_INPUT)
        cases = tuple(known[case_id] for case_id in case_ids)

    results: list[EvalResult] = []
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with open_catalog(settings, offline=False) as catalog:
            agent = ResearchAgent(chat, catalog)
            for case in cases:
                outcome = run_case(agent, case)
                results.append(outcome)
                tokens = outcome.result.completion.total_tokens if outcome.result else 0
                status = "PASS" if outcome.passed else "FAIL"
                typer.echo(f"{status} {case.id:<16} {outcome.latency_ms:>6}ms {tokens:>5} tok")
                for failure in outcome.failures:
                    typer.echo(f"     - {failure}")

    passed = sum(outcome.passed for outcome in results)
    tool_ok = sum(outcome.tool_use_correct for outcome in results)
    tokens = sum(o.result.completion.total_tokens for o in results if o.result is not None)
    latency = sum(outcome.latency_ms for outcome in results) // len(results)
    typer.echo(
        f"\n{passed}/{len(results)} passed | tool use correct {tool_ok}/{len(results)} | "
        f"{tokens} tokens | avg latency {latency}ms"
    )
    if passed != len(results):
        raise typer.Exit(EXIT_EVAL_FAILED)


def run() -> None:
    # Real environment variables take precedence over .env values.
    load_dotenv(find_dotenv(usecwd=True))
    app()
