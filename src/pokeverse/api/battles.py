"""Battle endpoints: battlers, damage and seeded battles between code players (no LLM)."""

import random
from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from pokeverse.api.app import Catalogs, MoveName, NameOrId, invalid_input
from pokeverse.battles import (
    MAX_MOVES,
    BattleEvent,
    Battler,
    battle_stats,
    calculate_damage,
    damage_range,
    default_battler,
    load_battler,
    make_player,
    run_battle,
)
from pokeverse.catalog import PokemonCatalog
from pokeverse.catalog.type_chart import effectiveness
from pokeverse.model import FrozenModel
from pokeverse.teams import MAX_TEAM_SIZE

router = APIRouter(tags=["battles"])

PlayerName = Literal["greedy", "random"]


class BattlerSpec(FrozenModel):
    pokemon: NameOrId
    moves: list[MoveName] = Field(
        default=[],
        max_length=MAX_MOVES,
        description="Move names; empty for the default moveset (fetches every learnable move).",
    )


class DamageRequest(FrozenModel):
    attacker: NameOrId
    move: NameOrId
    defender: NameOrId


class DamageReport(FrozenModel):
    """Level-50 damage without a critical hit, plus the critical-hit maximum."""

    attacker: str
    move: str
    defender: str
    min: int
    max: int
    critical_max: int
    defender_hp: int
    effectiveness: float
    stab: bool


TeamSpec = list[BattlerSpec]


class BattleRequest(FrozenModel):
    side1: TeamSpec = Field(min_length=1, max_length=MAX_TEAM_SIZE)
    side2: TeamSpec = Field(min_length=1, max_length=MAX_TEAM_SIZE)
    player1: PlayerName = "greedy"
    player2: PlayerName = "greedy"
    seed: int = 0


class BattleReport(FrozenModel):
    seed: int
    players: tuple[PlayerName, PlayerName]
    teams: tuple[TeamSpec, TeamSpec]
    winner: int | None = Field(description="0 or 1 for side 1 or 2; null for a draw.")
    turns: int
    events: tuple[BattleEvent, ...]


def _battler(catalog: PokemonCatalog, spec: BattlerSpec) -> Battler:
    if spec.moves:
        return load_battler(catalog, spec.pokemon, spec.moves)
    return default_battler(catalog, spec.pokemon)


def _spec(battler: Battler) -> BattlerSpec:
    return BattlerSpec(pokemon=battler.pokemon.name, moves=[move.name for move in battler.moves])


@router.post("/battlers", response_model=Battler)
def battler(spec: BattlerSpec, catalogs: Catalogs) -> Battler:
    """Validate a moveset, or compute the default one when no moves are given."""
    with catalogs() as catalog, invalid_input():
        return _battler(catalog, spec)


@router.post("/damage", response_model=DamageReport)
def damage(request: DamageRequest, catalogs: Catalogs) -> DamageReport:
    with catalogs() as catalog:
        attacker = catalog.get(request.attacker)
        defender = catalog.get(request.defender)
        move = catalog.get_move(request.move)
    with invalid_input():
        low, high = damage_range(attacker, defender, move)
        critical = calculate_damage(attacker, defender, move, critical=True)
    return DamageReport(
        attacker=attacker.name,
        move=move.name,
        defender=defender.name,
        min=low,
        max=high,
        critical_max=critical,
        defender_hp=battle_stats(defender.stats).hp,
        effectiveness=effectiveness(move.type, defender.types),
        stab=move.type in attacker.types,
    )


@router.post("/battles", response_model=BattleReport)
def battle(request: BattleRequest, catalogs: Catalogs) -> BattleReport:
    """One seeded battle between code players; the same request always gives the same result."""
    with catalogs() as catalog, invalid_input():
        teams = [
            [_battler(catalog, spec) for spec in side] for side in (request.side1, request.side2)
        ]
    players = (
        make_player(request.player1, random.Random(f"{request.seed}:1")),
        make_player(request.player2, random.Random(f"{request.seed}:2")),
    )
    result = run_battle(teams[0], teams[1], players, random.Random(request.seed))
    return BattleReport(
        seed=request.seed,
        players=(request.player1, request.player2),
        teams=([_spec(b) for b in teams[0]], [_spec(b) for b in teams[1]]),
        winner=result.winner,
        turns=result.turns,
        events=result.events,
    )
