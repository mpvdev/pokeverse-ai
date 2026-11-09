"""Command-line interface for PokéVerse AI."""

import json
import random
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, cast

import typer
from dotenv import find_dotenv, load_dotenv

from pokeverse.agents import (
    POKEDEX_ANSWER_SCHEMA,
    BattleStrategyAgent,
    OpponentAnalysis,
    OpponentAnalysisAgent,
    PokedexAnswer,
    ResearchAgent,
    Supervisor,
    TeamCompositionAgent,
    TeamOptimizationAgent,
    make_catalog_tools,
    normalize_identifier,
)
from pokeverse.agents.supervisor import OptimizeMode
from pokeverse.battles import (
    MAX_MOVES,
    PLAYER_NAMES,
    Battler,
    BattleResult,
    Player,
    battle_stats,
    calculate_damage,
    damage_range,
    default_battler,
    load_battler,
    make_player,
    run_battle,
)
from pokeverse.catalog import (
    CatalogError,
    Move,
    MoveNotInCatalogError,
    Pokemon,
    PokemonCatalog,
    PokemonNotInCatalogError,
    SqlitePokemonRepository,
    UpstreamUnavailableError,
)
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.catalog.type_chart import effectiveness
from pokeverse.evals import RESEARCH_CASES, EvalResult, run_case
from pokeverse.evals.battles import (
    BATTLE_SCENARIOS,
    BATTLE_SYSTEMS,
    LLM_SYSTEMS,
    BattleScenario,
    SystemReport,
    feedback_experiment,
    run_system,
)
from pokeverse.evals.compare import COMPARE_CASES, SYSTEMS
from pokeverse.evals.compare import run_case as compare_case
from pokeverse.llm import (
    Completion,
    LlmAuthError,
    LlmRequestError,
    LlmSettings,
    LlmUnavailableError,
    OpenAIChat,
)
from pokeverse.paths import default_db_path
from pokeverse.teams import MAX_TEAM_SIZE, Team, TeamAnalysis, analyze_team

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
def open_catalog(settings: Settings) -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(settings.db_path) as repository, PokeApiClient() as client:
        yield PokemonCatalog(repository, client)


def format_pokemon(pokemon: Pokemon) -> str:
    types = " / ".join(pokemon_type.value.title() for pokemon_type in pokemon.types)
    return f"#{pokemon.pokedex_id:04d} {pokemon.display_name} — {types}"


def format_stats(pokemon: Pokemon) -> str:
    s = pokemon.stats
    return (
        f"HP {s.hp} / Atk {s.attack} / Def {s.defense} / SpA {s.special_attack} / "
        f"SpD {s.special_defense} / Spe {s.speed} (total {s.total})"
    )


def format_move(move: Move) -> str:
    power = move.power if move.power is not None else "—"
    accuracy = f"{move.accuracy}%" if move.accuracy is not None else "never misses"
    priority = f"{move.priority:+d}" if move.priority else "0"
    return (
        f"#{move.move_id:04d} {move.display_name} — {move.type.value.title()}, "
        f"{move.damage_class.value}, power {power}, accuracy {accuracy}, "
        f"priority {priority}, PP {move.pp}"
    )


def fail(message: str, code: int) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code)


def resolve_battler(catalog: PokemonCatalog, pokemon: str, moves: list[str]) -> Battler:
    identifier = normalize_identifier(pokemon)
    if not moves:
        return default_battler(catalog, identifier)
    move_names = [normalize_identifier(move) for move in moves]
    if any(isinstance(name, int) for name in move_names):
        raise ValueError("moves must be given by name")
    return load_battler(catalog, identifier, cast(list[str], move_names))


def parse_member(spec: str) -> tuple[str, list[str]]:
    pokemon, _, moves = spec.partition(":")
    return pokemon, [move for move in moves.split(",") if move.strip()]


def format_battler(battler: Battler) -> str:
    moves = ", ".join(move.display_name for move in battler.moves)
    return f"{battler.pokemon.display_name} [{moves}]"


BATTLE_PLAYERS = (*PLAYER_NAMES, "agent")


def make_battle_player(
    name: str, seed: str, chat: OpenAIChat | None, analysis: OpponentAnalysis | None
) -> Player:
    if name == "agent":
        if chat is None:
            raise ValueError("the agent player needs an LLM client")
        return BattleStrategyAgent(chat, analysis=analysis)
    return make_player(name, random.Random(seed))


def print_analysis_report(analysis: OpponentAnalysis) -> None:
    for threat in analysis.threats:
        typer.echo(f"  threat {threat.foe} [{threat.danger}]: {threat.reason}")
    for counter in analysis.counters:
        status = "verified" if counter.verified else "NOT supported by the matchups"
        typer.echo(f"  counter {counter.answer} -> {counter.threat} ({status}): {counter.reason}")
    typer.echo(f"  plan: {analysis.plan}")


@app.command("pokemon")
def pokemon_command(
    ctx: typer.Context,
    name_or_id: Annotated[str, typer.Argument(help="Pokémon name (e.g. pikachu) or Pokédex id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Look up a Pokémon on PokéAPI (synced to the local database)."""
    settings: Settings = ctx.obj
    try:
        identifier = normalize_identifier(name_or_id)
        with open_catalog(settings) as catalog:
            pokemon = catalog.get(identifier)
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except PokemonNotInCatalogError as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    if as_json:
        typer.echo(json.dumps(pokemon.to_dict()))
    else:
        typer.echo(format_pokemon(pokemon))
        typer.echo(format_stats(pokemon))


@app.command("list")
def list_command(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100, help="Page size.")] = 20,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Entries to skip.")] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """List Pokémon names and ids from PokéAPI, one page at a time."""
    settings: Settings = ctx.obj
    try:
        with open_catalog(settings) as catalog:
            page = catalog.index(limit, offset)
    except CatalogError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    if as_json:
        typer.echo(json.dumps(page.model_dump(mode="json")))
        return
    for entry in page.results:
        typer.echo(f"#{entry.pokedex_id:04d} {entry.name}")
    shown = f"{offset + 1}-{offset + len(page.results)}" if page.results else "none"
    typer.echo(f"({shown} of {page.count})")


@app.command("move")
def move_command(
    ctx: typer.Context,
    name_or_id: Annotated[str, typer.Argument(help="Move name (e.g. 'Swords Dance') or id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Look up a move on PokéAPI (synced to the local database)."""
    settings: Settings = ctx.obj
    try:
        identifier = normalize_identifier(name_or_id)
        with open_catalog(settings) as catalog:
            move = catalog.get_move(identifier)
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except MoveNotInCatalogError as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    typer.echo(json.dumps(move.to_dict()) if as_json else format_move(move))


@app.command("learnset")
def learnset_command(
    ctx: typer.Context,
    name_or_id: Annotated[str, typer.Argument(help="Pokémon name (e.g. pikachu) or Pokédex id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """List the moves a Pokémon can learn (names only; no move lookups)."""
    settings: Settings = ctx.obj
    try:
        identifier = normalize_identifier(name_or_id)
        with open_catalog(settings) as catalog:
            pokemon = catalog.get(identifier)
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except PokemonNotInCatalogError as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    names = sorted(pokemon.learnset)
    if as_json:
        typer.echo(json.dumps({"pokemon": pokemon.name, "learnset": names}))
    else:
        plural = "" if len(names) == 1 else "s"
        typer.echo(f"{format_pokemon(pokemon)} — {len(names)} learnable move{plural}")
        typer.echo(", ".join(names))


@app.command("moveset")
def moveset_command(
    ctx: typer.Context,
    pokemon: Annotated[str, typer.Argument(help="Pokémon name or Pokédex id.")],
    moves: Annotated[
        list[str] | None,
        typer.Argument(help=f"1-{MAX_MOVES} move names; omit for the default moveset."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Check a battle moveset, or show the default one (fetches every learnable move)."""
    settings: Settings = ctx.obj
    try:
        if moves and len(moves) > MAX_MOVES:
            raise ValueError(f"a battler must have between 1 and {MAX_MOVES} moves")
        with open_catalog(settings) as catalog:
            battler = resolve_battler(catalog, pokemon, moves or [])
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except (PokemonNotInCatalogError, MoveNotInCatalogError) as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    if as_json:
        typer.echo(json.dumps(battler.to_dict()))
    else:
        typer.echo(format_pokemon(battler.pokemon))
        for move in battler.moves:
            typer.echo(f"  {format_move(move)}")


@app.command("damage")
def damage_command(
    ctx: typer.Context,
    attacker: Annotated[str, typer.Argument(help="Attacking Pokémon.")],
    move: Annotated[str, typer.Argument(help="Move used by the attacker.")],
    defender: Annotated[str, typer.Argument(help="Defending Pokémon.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Damage range of one move at level 50 (no critical hit), plus the critical-hit maximum."""
    settings: Settings = ctx.obj
    try:
        with open_catalog(settings) as catalog:
            source = catalog.get(normalize_identifier(attacker))
            target = catalog.get(normalize_identifier(defender))
            used = catalog.get_move(normalize_identifier(move))
        low, high = damage_range(source, target, used)
        critical = calculate_damage(source, target, used, critical=True)
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID_INPUT) from error
    except (PokemonNotInCatalogError, MoveNotInCatalogError) as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error
    except UpstreamUnavailableError as error:
        raise fail(str(error), EXIT_UPSTREAM_UNAVAILABLE) from error

    hp = battle_stats(target.stats).hp
    multiplier = effectiveness(used.type, target.types)
    if as_json:
        result = {
            "attacker": source.name,
            "move": used.name,
            "defender": target.name,
            "min": low,
            "max": high,
            "critical_max": critical,
            "defender_hp": hp,
            "effectiveness": multiplier,
            "stab": used.type in source.types,
        }
        typer.echo(json.dumps(result))
        return
    stab = ", STAB" if used.type in source.types else ""
    typer.echo(
        f"{source.display_name} {used.display_name} vs {target.display_name}: "
        f"{low}-{high} damage ({low / hp:.0%}-{high / hp:.0%} of {hp} HP), "
        f"{multiplier:g}x{stab}; critical hit up to {critical}"
    )


@app.command("battle")
def battle_command(
    ctx: typer.Context,
    side1: Annotated[
        list[str],
        typer.Option(
            "--side1",
            help="Side 1 member: 'name' (default moveset) or 'name:move,move'; repeat per member.",
        ),
    ],
    side2: Annotated[
        list[str],
        typer.Option("--side2", help="A side 2 member, same format as --side1."),
    ],
    player1: Annotated[
        str, typer.Option("--player1", help=f"Side 1 player: {', '.join(BATTLE_PLAYERS)}.")
    ] = "greedy",
    player2: Annotated[
        str, typer.Option("--player2", help=f"Side 2 player: {', '.join(BATTLE_PLAYERS)}.")
    ] = "greedy",
    seed: Annotated[int, typer.Option("--seed", help="Random seed of the first battle.")] = 0,
    runs: Annotated[
        int, typer.Option("--runs", min=1, help="Number of battles (seeds seed, seed+1, ...).")
    ] = 1,
    analysis: Annotated[
        bool,
        typer.Option(
            "--analysis/--no-analysis",
            help="Brief agent players with a pre-battle Opponent Analysis Agent run.",
        ),
    ] = True,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Simulate battles; players are code (greedy, random) or the Battle Strategy Agent (LLM)."""
    settings: Settings = ctx.obj
    names = (player1, player2)
    results: list[tuple[int, BattleResult, list[BattleStrategyAgent]]] = []
    analyses: dict[int, OpponentAnalysis] = {}
    try:
        with llm_errors():
            for name in names:
                if name not in BATTLE_PLAYERS:
                    raise ValueError(
                        f"unknown player {name!r}; choose from {', '.join(BATTLE_PLAYERS)}"
                    )
            for side in (side1, side2):
                if len(side) > MAX_TEAM_SIZE:
                    raise ValueError(
                        f"a battle team must have between 1 and {MAX_TEAM_SIZE} battlers"
                    )
            chat = OpenAIChat(LlmSettings.from_env()) if "agent" in names else None
            with open_catalog(settings) as catalog:
                teams = [
                    [resolve_battler(catalog, *parse_member(spec)) for spec in side]
                    for side in (side1, side2)
                ]
            if chat is not None and analysis:
                for side, name in enumerate(names):
                    if name == "agent":
                        analyst = OpponentAnalysisAgent(chat)
                        analyses[side] = analyst.analyze(teams[side], teams[1 - side])
            for battle_seed in range(seed, seed + runs):
                players = (
                    make_battle_player(player1, f"{battle_seed}:1", chat, analyses.get(0)),
                    make_battle_player(player2, f"{battle_seed}:2", chat, analyses.get(1)),
                )
                result = run_battle(teams[0], teams[1], players, random.Random(battle_seed))
                agents = [p for p in players if isinstance(p, BattleStrategyAgent)]
                results.append((battle_seed, result, agents))
    except (PokemonNotInCatalogError, MoveNotInCatalogError) as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error

    team_names = [
        [{"pokemon": b.pokemon.name, "moves": [m.name for m in b.moves]} for b in team]
        for team in teams
    ]
    agent_tokens = sum(agent.total_tokens for _, _, agents in results for agent in agents)
    analysis_tokens = sum(a.completion.total_tokens for a in analyses.values())
    fallbacks = sum(agent.fallbacks for _, _, agents in results for agent in agents)
    if runs == 1:
        battle_seed, result, agents = results[0]
        decisions = sorted(
            (decision for agent in agents for decision in agent.decisions),
            key=lambda decision: (decision.turn, decision.side),
        )
        if as_json:
            report = {
                "seed": battle_seed,
                "players": list(names),
                "teams": team_names,
                "winner": result.winner,
                "turns": result.turns,
                "events": [event.to_dict() for event in result.events],
                "decisions": [decision.to_dict() for decision in decisions],
                "agent_tokens": agent_tokens,
                "analyses": {str(side): a.to_dict() for side, a in analyses.items()},
                "analysis_tokens": analysis_tokens,
            }
            typer.echo(json.dumps(report))
            return
        for index, team in enumerate(teams):
            members = ", ".join(format_battler(battler) for battler in team)
            typer.echo(f"Side {index + 1} ({names[index]}): {members}")
        for side, side_analysis in analyses.items():
            typer.echo(f"Side {side + 1} pre-battle analysis:")
            print_analysis_report(side_analysis)
        for event in result.events:
            typer.echo(f"[{event.turn}] {event.describe()}")
        if result.winner is None:
            typer.echo(f"Draw after {result.turns} turns.")
        else:
            winner = result.winner
            typer.echo(f"Winner: Side {winner + 1} ({names[winner]}) after {result.turns} turns.")
        if decisions:
            typer.echo("Agent decisions:")
            for decision in decisions:
                marker = " [fallback: greedy]" if decision.fallback else ""
                typer.echo(
                    f"  turn {decision.turn}, side {decision.side + 1}: "
                    f"{decision.action}{marker} — {decision.reason}"
                )
            typer.echo(
                f"Agent tokens: {agent_tokens} (+{analysis_tokens} analysis); "
                f"fallbacks: {fallbacks}."
            )
        return

    wins = [sum(1 for _, r, _ in results if r.winner == side) for side in (0, 1)]
    draws = runs - sum(wins)
    average = sum(r.turns for _, r, _ in results) / runs
    if as_json:
        report = {
            "runs": runs,
            "players": list(names),
            "teams": team_names,
            "wins": wins,
            "draws": draws,
            "average_turns": average,
            "agent_tokens": agent_tokens,
            "agent_fallbacks": fallbacks,
            "analysis_tokens": analysis_tokens,
            "results": [{"seed": s, "winner": r.winner, "turns": r.turns} for s, r, _ in results],
        }
        typer.echo(json.dumps(report))
        return
    typer.echo(
        f"{runs} battles (seeds {seed}-{seed + runs - 1}): "
        f"Side 1 ({names[0]}) won {wins[0]}, Side 2 ({names[1]}) won {wins[1]}, "
        f"draws {draws}; average {average:.1f} turns."
    )
    if "agent" in names:
        typer.echo(
            f"Agent tokens: {agent_tokens} (+{analysis_tokens} analysis); fallbacks: {fallbacks}."
        )


@app.command("scout")
def scout_command(
    ctx: typer.Context,
    side1: Annotated[
        list[str],
        typer.Option("--side1", help="Our member: 'name' or 'name:move,move'; repeat per member."),
    ],
    side2: Annotated[
        list[str],
        typer.Option("--side2", help="An opposing member, same format as --side1."),
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    show_usage: Annotated[
        bool, typer.Option("--usage", help="Print token usage to stderr.")
    ] = False,
) -> None:
    """Ask the Opponent Analysis Agent to rank side 2's threats to side 1; code checks counters."""
    settings: Settings = ctx.obj
    try:
        with llm_errors():
            for side in (side1, side2):
                if len(side) > MAX_TEAM_SIZE:
                    raise ValueError(
                        f"a battle team must have between 1 and {MAX_TEAM_SIZE} battlers"
                    )
            chat = OpenAIChat(LlmSettings.from_env())
            with open_catalog(settings) as catalog:
                own = [resolve_battler(catalog, *parse_member(spec)) for spec in side1]
                foe = [resolve_battler(catalog, *parse_member(spec)) for spec in side2]
            result = OpponentAnalysisAgent(chat).analyze(own, foe)
    except (PokemonNotInCatalogError, MoveNotInCatalogError) as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error

    if as_json:
        typer.echo(json.dumps(result.to_dict()))
    else:
        typer.echo(f"Side 2 threats to side 1 ({', '.join(b.pokemon.name for b in own)}):")
        print_analysis_report(result)
        typer.echo("\nBriefing handed to the Battle Strategy Agent:")
        typer.echo(result.briefing())
    if show_usage:
        print_usage(result.completion)


def select_scenarios(ids: list[str] | None) -> tuple[BattleScenario, ...]:
    if not ids:
        return BATTLE_SCENARIOS
    known = {scenario.id: scenario for scenario in BATTLE_SCENARIOS}
    unknown = [scenario_id for scenario_id in ids if scenario_id not in known]
    if unknown:
        raise ValueError(f"unknown scenario(s) {unknown}; known: {sorted(known)}")
    return tuple(known[scenario_id] for scenario_id in ids)


def load_scenario(
    catalog: PokemonCatalog, scenario: BattleScenario
) -> tuple[list[Battler], list[Battler]]:
    return (
        [resolve_battler(catalog, name, []) for name in scenario.side1],
        [resolve_battler(catalog, name, []) for name in scenario.side2],
    )


def report_line(report: SystemReport) -> str:
    low, high = report.interval
    return (
        f"  {report.system:<15} {report.wins:>2}/{report.battles:<3} "
        f"{report.win_rate:>4.0%} ({low:.0%}-{high:.0%})  "
        f"turns {report.average_turns:4.1f}  mistakes/battle {report.mistakes_per_battle:4.2f}  "
        f"tokens/battle {report.tokens_per_battle:7.0f}  fallbacks {report.fallbacks}"
    )


def progress_to_stderr(prefix: str) -> Callable[[str], None]:
    return lambda message: typer.echo(f"[{prefix}] {message}", err=True)


@app.command("battle-eval")
def battle_eval_command(
    ctx: typer.Context,
    scenario_ids: Annotated[
        list[str] | None, typer.Option("--scenario", help="Scenario id (repeatable).")
    ] = None,
    systems: Annotated[
        list[str] | None,
        typer.Option("--system", help=f"Side 1 player (repeatable): {', '.join(BATTLE_SYSTEMS)}."),
    ] = None,
    seeds: Annotated[int, typer.Option("--seeds", min=1, help="Battles per system.")] = 5,
    seed_start: Annotated[int, typer.Option("--seed-start", help="First seed.")] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Win rate (95% CI), mistakes and tokens of each system against greedy; LLM systems cost."""
    settings: Settings = ctx.obj
    chosen = tuple(systems or BATTLE_SYSTEMS)
    battle_seeds = range(seed_start, seed_start + seeds)
    reports: dict[str, list[SystemReport]] = {}
    try:
        with llm_errors():
            unknown = [system for system in chosen if system not in BATTLE_SYSTEMS]
            if unknown:
                raise ValueError(f"unknown system(s) {unknown}; known: {list(BATTLE_SYSTEMS)}")
            scenarios = select_scenarios(scenario_ids)
            needs_llm = any(system in LLM_SYSTEMS for system in chosen)
            chat = OpenAIChat(LlmSettings.from_env()) if needs_llm else None
            for scenario in scenarios:
                with open_catalog(settings) as catalog:
                    team, opponent = load_scenario(catalog, scenario)
                reports[scenario.id] = [
                    run_system(
                        system,
                        team,
                        opponent,
                        battle_seeds,
                        chat,
                        progress=progress_to_stderr(scenario.id),
                    )
                    for system in chosen
                ]
    except (PokemonNotInCatalogError, MoveNotInCatalogError) as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error

    if as_json:
        payload = {
            scenario_id: [report.to_dict() for report in scenario_reports]
            for scenario_id, scenario_reports in reports.items()
        }
        typer.echo(json.dumps({"seeds": list(battle_seeds), "scenarios": payload}))
        return
    for scenario in scenarios:
        typer.echo(
            f"Scenario {scenario.id}: {', '.join(scenario.side1)} vs "
            f"{', '.join(scenario.side2)} (side 2: greedy). {scenario.description}"
        )
        for report in reports[scenario.id]:
            typer.echo(report_line(report))


@app.command("battle-feedback")
def battle_feedback_command(
    ctx: typer.Context,
    scenario_id: Annotated[str, typer.Option("--scenario", help="Scenario id.")] = "bulk",
    train: Annotated[int, typer.Option("--train", min=1, help="Training battles.")] = 5,
    test: Annotated[int, typer.Option("--test", min=1, help="Test battles per system.")] = 5,
    seed_start: Annotated[int, typer.Option("--seed-start", help="First seed.")] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Learn lessons from the agent's mistakes on training seeds; measure them on new seeds."""
    settings: Settings = ctx.obj
    train_seeds = range(seed_start, seed_start + train)
    test_seeds = range(seed_start + train, seed_start + train + test)
    try:
        with llm_errors():
            (scenario,) = select_scenarios([scenario_id])
            chat = OpenAIChat(LlmSettings.from_env())
            with open_catalog(settings) as catalog:
                team, opponent = load_scenario(catalog, scenario)
            report = feedback_experiment(
                team,
                opponent,
                chat,
                train_seeds,
                test_seeds,
                progress=progress_to_stderr(scenario.id),
            )
    except (PokemonNotInCatalogError, MoveNotInCatalogError) as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error

    if as_json:
        typer.echo(json.dumps(report.to_dict()))
        return
    typer.echo(f"Training (seeds {train_seeds.start}-{train_seeds.stop - 1}):")
    typer.echo(report_line(report.training))
    for mistake in report.training.mistakes:
        typer.echo(f"    [{mistake.kind}] {mistake.describe()}")
    if not report.review.lessons:
        typer.echo("No lessons: no mistakes were detected, so the test battles were skipped.")
        return
    typer.echo(f"Lessons ({report.review_tokens} tokens):")
    for lesson in report.review.lessons:
        typer.echo(f"  - {lesson.text} (evidence: {', '.join(lesson.evidence)})")
    typer.echo(f"Test (seeds {test_seeds.start}-{test_seeds.stop - 1}):")
    if report.baseline:
        typer.echo(report_line(report.baseline))
    if report.with_lessons:
        typer.echo(report_line(report.with_lessons))


@app.command("team")
def team_command(
    ctx: typer.Context,
    names: Annotated[
        list[str], typer.Argument(help="1-6 Pokémon names or Pokédex ids (repeats allowed).")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Analyze a team's type weaknesses and coverage (deterministic, no LLM)."""
    settings: Settings = ctx.obj
    if len(names) > MAX_TEAM_SIZE:
        raise fail(f"a team can have at most {MAX_TEAM_SIZE} Pokémon", EXIT_INVALID_INPUT)
    try:
        with open_catalog(settings) as catalog:
            members = tuple(catalog.get(normalize_identifier(name)) for name in names)
        analysis = analyze_team(Team(members=members))
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
    print_analysis(analysis)


def print_analysis(analysis: TeamAnalysis) -> None:
    typer.echo("Vulnerable to:" + ("" if analysis.vulnerabilities else " none"))
    for exposure in analysis.vulnerabilities:
        cover = ", ".join(exposure.resists + exposure.immune) or "nobody"
        weak = ", ".join(exposure.weak)
        typer.echo(f"  {exposure.attacking_type:<9} weak: {weak} | resisted by: {cover}")
    typer.echo("Unresisted attack types: " + (", ".join(analysis.unresisted) or "none"))
    typer.echo("Offensive gaps (STAB): " + (", ".join(analysis.offensive_gaps) or "none"))


@app.command("build")
def build_command(
    ctx: typer.Context,
    request: Annotated[str, typer.Argument(help="What the team should be, in plain words.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    show_usage: Annotated[
        bool, typer.Option("--usage", help="Print tool calls and token usage to stderr.")
    ] = False,
) -> None:
    """Ask the Team Composition Agent to build a team; our code re-checks the result."""
    settings: Settings = ctx.obj
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with open_catalog(settings) as catalog:
            result = TeamCompositionAgent(chat, catalog).build(request)

    if as_json:
        typer.echo(json.dumps(result.to_dict()))
    else:
        members = zip(result.analysis.team.members, result.proposal.members, strict=True)
        for pokemon, choice in members:
            types = "/".join(t.value for t in pokemon.types)
            typer.echo(f"  {pokemon.display_name:<14} {types:<16} {choice.role}")
        typer.echo(f"\n{result.proposal.summary}\n")
        print_analysis(result.analysis)
    if not result.self_checked:
        typer.echo("Warning: the agent did not analyze this exact team before answering", err=True)
    if show_usage:
        print_usage(result.completion)


@app.command("optimize")
def optimize_command(
    ctx: typer.Context,
    names: Annotated[list[str], typer.Argument(help="The team: 1-6 Pokémon names or ids.")],
    goal: Annotated[str, typer.Option("--goal", help="What the team should achieve.")] = "",
    keep: Annotated[
        list[str] | None, typer.Option("--keep", help="Never swap out this member (repeatable).")
    ] = None,
    notes: Annotated[
        str, typer.Option("--notes", help="Claims about the team to fact-check.")
    ] = "",
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    show_usage: Annotated[
        bool, typer.Option("--usage", help="Print tool calls and token usage to stderr.")
    ] = False,
) -> None:
    """Ask the Team Optimization Agent to fact-check and improve a team."""
    settings: Settings = ctx.obj
    if len(names) > MAX_TEAM_SIZE:
        raise fail(f"a team can have at most {MAX_TEAM_SIZE} Pokémon", EXIT_INVALID_INPUT)
    try:
        with llm_errors():
            chat = OpenAIChat(LlmSettings.from_env())
            with open_catalog(settings) as catalog:
                team = Team(members=tuple(catalog.get(normalize_identifier(n)) for n in names))
                result = TeamOptimizationAgent(chat, catalog).optimize(
                    team, goal=goal, keep=keep or (), notes=notes
                )
    except PokemonNotInCatalogError as error:
        raise fail(str(error), EXIT_NOT_FOUND) from error

    if as_json:
        typer.echo(json.dumps(result.to_dict()))
    else:
        typer.echo(
            f"Before: {', '.join(result.original.team.names)}  score {result.original.score}"
        )
        for swap in result.swaps:
            status = "ACCEPTED" if swap.accepted else "REJECTED"
            typer.echo(f"  {status} {swap.out} -> {swap.into}: {swap.reason} [{swap.verdict}]")
        typer.echo(f"After:  {', '.join(result.final.team.names)}  score {result.final.score}")
        print_analysis(result.final)
        if result.claims:
            typer.echo("Claims:")
        for claim in result.claims:
            status = "ok   " if claim.correct else "WRONG"
            actual = (
                f"{claim.actual} ({claim.multiplier:g}x)" if claim.actual else "unknown Pokémon"
            )
            typer.echo(
                f"  {status} {claim.member} vs {claim.attacking_type}: "
                f"claimed {claim.claimed}, actually {actual}"
            )
        typer.echo(f"\n{result.critique}")
    if show_usage:
        print_usage(result.completion)


@app.command("advise")
def advise_command(
    ctx: typer.Context,
    request: Annotated[str, typer.Argument(help="Any Pokémon question or team request.")],
    optimize: Annotated[
        str,
        typer.Option(
            "--optimize",
            help="When to run the Team Optimization Agent after building: "
            "auto (only if the team has vulnerabilities), always, or never.",
        ),
    ] = "auto",
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    show_usage: Annotated[
        bool, typer.Option("--usage", help="Print delegations and token usage to stderr.")
    ] = False,
) -> None:
    """Ask the Supervisor, which delegates to the research and team-building agents."""
    settings: Settings = ctx.obj
    with llm_errors():
        supervisor_mode = cast("OptimizeMode", optimize)
        chat = OpenAIChat(LlmSettings.from_env())
        with open_catalog(settings) as catalog:
            result = Supervisor(chat, catalog, optimize=supervisor_mode).run(request)

    typer.echo(json.dumps(result.to_dict()) if as_json else result.answer)
    if show_usage:
        for delegation in result.delegations:
            outcome = f"error: {delegation.error}" if delegation.error else "ok"
            handoff = f" (handoff: {', '.join(delegation.handoff)})" if delegation.handoff else ""
            typer.echo(
                f"[delegate] {delegation.agent}: {delegation.task!r}{handoff} -> {outcome} "
                f"({delegation.tokens} tokens)",
                err=True,
            )
        typer.echo(
            f"[{result.completion.model_id}] tokens supervisor={result.completion.total_tokens} "
            f"specialists={result.specialist_tokens} total={result.total_tokens} "
            f"latency={result.completion.latency_ms}ms",
            err=True,
        )


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
    """Ask the LLM a question, letting it look up Pokémon in the catalog."""
    settings: Settings = ctx.obj
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with ExitStack() as stack:
            tools = ()
            if use_tools:
                catalog = stack.enter_context(open_catalog(settings))
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
    except UpstreamUnavailableError as error:
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
    """Ask the Pokémon Research Agent; answers are grounded in catalog lookups."""
    settings: Settings = ctx.obj
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with open_catalog(settings) as catalog:
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
        with open_catalog(settings) as catalog:
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


@app.command("compare")
def compare_command(
    ctx: typer.Context,
    case_ids: Annotated[
        list[str] | None, typer.Option("--case", help="Run only this case id (repeatable).")
    ] = None,
    systems: Annotated[
        list[str] | None,
        typer.Option("--system", help=f"Run only this system (repeatable): {', '.join(SYSTEMS)}."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Compare single- and multi-agent systems on fixed tasks (live; costs many tokens)."""
    settings: Settings = ctx.obj
    known = {case.id: case for case in COMPARE_CASES}
    unknown = [c for c in case_ids or () if c not in known] + [
        s for s in systems or () if s not in SYSTEMS
    ]
    if unknown:
        raise fail(
            f"unknown case/system {unknown}; cases: {sorted(known)}; systems: {list(SYSTEMS)}",
            EXIT_INVALID_INPUT,
        )
    cases = [known[c] for c in case_ids] if case_ids else list(COMPARE_CASES)
    chosen = [s for s in SYSTEMS if s in systems] if systems else list(SYSTEMS)

    outcomes = []
    aborted: Exception | None = None
    with llm_errors():
        chat = OpenAIChat(LlmSettings.from_env())
        with open_catalog(settings) as catalog:
            for case in cases:
                for system in chosen:
                    try:
                        outcome = compare_case(system, case, chat, catalog)
                    except (LlmAuthError, LlmUnavailableError, UpstreamUnavailableError) as error:
                        aborted = error
                        break
                    outcomes.append(outcome)
                    status = "PASS" if outcome.passed else "FAIL"
                    score = outcome.analysis.score if outcome.analysis else "-"
                    # With --json, progress goes to stderr so stdout stays valid JSON.
                    typer.echo(
                        f"{status} {case.id:<14} {system:<10} {outcome.tokens:>6} tok "
                        f"{outcome.latency_ms / 1000:>5.1f}s  score {score}",
                        err=as_json,
                    )
                    for failure in outcome.failures:
                        typer.echo(f"     - {failure}", err=as_json)
                if aborted:
                    break

    summary = []
    for system in chosen:
        runs = [o for o in outcomes if o.system == system]
        if not runs:
            continue
        summary.append(
            {
                "system": system,
                "passed": sum(o.passed for o in runs),
                "runs": len(runs),
                "tokens": sum(o.tokens for o in runs),
                "avg_latency_ms": sum(o.latency_ms for o in runs) // len(runs),
            }
        )
    if as_json:
        report = {"runs": [o.to_dict() for o in outcomes], "summary": summary}
        typer.echo(json.dumps({**report, "aborted": str(aborted) if aborted else None}))
    else:
        typer.echo("")
        for row in summary:
            typer.echo(
                f"{row['system']:<10} passed {row['passed']}/{row['runs']} | "
                f"tokens {row['tokens']} (avg {row['tokens'] // row['runs']}) | "
                f"avg latency {row['avg_latency_ms'] / 1000:.1f}s"
            )
    if aborted:
        # Re-raise through the usual mapping so the exit code reflects the cause.
        with llm_errors():
            raise aborted


def run() -> None:
    # Real environment variables take precedence over .env values.
    load_dotenv(find_dotenv(usecwd=True))
    app()
