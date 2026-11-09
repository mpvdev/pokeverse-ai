from collections.abc import Iterator

import pytest

from pokeverse.catalog import (
    BaseStats,
    DamageClass,
    Move,
    MoveNotInCatalogError,
    Pokemon,
    PokemonCatalog,
    PokemonNotInCatalogError,
    PokemonType,
    SqlitePokemonRepository,
    UpstreamUnavailableError,
)
from pokeverse.catalog.pokeapi import (
    PokeApiError,
    PokeApiRateLimitedError,
    PokeApiResponseError,
    PokeApiUnavailableError,
    PokemonNotFoundError,
)

PIKACHU = Pokemon(
    pokedex_id=25,
    name="pikachu",
    types=(PokemonType.ELECTRIC,),
    stats=BaseStats(hp=35, attack=55, defense=40, special_attack=50, special_defense=50, speed=90),
)
CHARIZARD = Pokemon(
    pokedex_id=6,
    name="charizard",
    types=(PokemonType.FIRE, PokemonType.FLYING),
    stats=BaseStats(
        hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100
    ),
)
THUNDERBOLT = Move(
    move_id=85,
    name="thunderbolt",
    type=PokemonType.ELECTRIC,
    damage_class=DamageClass.SPECIAL,
    power=90,
    accuracy=100,
    priority=0,
    pp=15,
)


class FakeSource:
    """In-memory upstream that records calls and can simulate outages."""

    def __init__(self, *pokemon: Pokemon, moves: tuple[Move, ...] = ()) -> None:
        self._by_key: dict[str | int, Pokemon] = {}
        for entry in pokemon:
            self._by_key[entry.name] = entry
            self._by_key[entry.pokedex_id] = entry
        self._moves: dict[str | int, Move] = {}
        for move in moves:
            self._moves[move.name] = move
            self._moves[move.move_id] = move
        self.calls: list[str | int] = []
        self.move_calls: list[str | int] = []
        self.failure: PokeApiError | None = None

    def fetch_pokemon(self, name_or_id: str | int) -> Pokemon:
        self.calls.append(name_or_id)
        if self.failure is not None:
            raise self.failure
        if name_or_id not in self._by_key:
            raise PokemonNotFoundError(str(name_or_id))
        return self._by_key[name_or_id]

    def fetch_move(self, name_or_id: str | int) -> Move:
        self.move_calls.append(name_or_id)
        if self.failure is not None:
            raise self.failure
        if name_or_id not in self._moves:
            raise PokemonNotFoundError(str(name_or_id))
        return self._moves[name_or_id]


@pytest.fixture
def repository() -> Iterator[SqlitePokemonRepository]:
    with SqlitePokemonRepository(":memory:") as repo:
        yield repo


@pytest.fixture
def source() -> FakeSource:
    return FakeSource(PIKACHU, CHARIZARD, moves=(THUNDERBOLT,))


@pytest.fixture
def catalog(repository: SqlitePokemonRepository, source: FakeSource) -> PokemonCatalog:
    return PokemonCatalog(repository, source)


def test_miss_imports_from_source_and_stores(
    catalog: PokemonCatalog, repository: SqlitePokemonRepository, source: FakeSource
) -> None:
    assert catalog.get("pikachu") == PIKACHU
    assert source.calls == ["pikachu"]
    assert repository.get_by_id(25) == PIKACHU


def test_hit_does_not_call_source(catalog: PokemonCatalog, source: FakeSource) -> None:
    catalog.get("pikachu")
    catalog.get("pikachu")
    catalog.get(25)
    catalog.get("  Pikachu ")

    assert source.calls == ["pikachu"]


def test_lookup_by_id_imports_by_id(catalog: PokemonCatalog, source: FakeSource) -> None:
    assert catalog.get(6) == CHARIZARD
    assert source.calls == [6]
    assert catalog.get("charizard") == CHARIZARD
    assert source.calls == [6]


def test_cached_pokemon_survive_upstream_outage(
    catalog: PokemonCatalog, source: FakeSource
) -> None:
    catalog.get("charizard")
    source.failure = PokeApiUnavailableError("down")

    assert catalog.get("charizard") == CHARIZARD
    assert catalog.get(6) == CHARIZARD


@pytest.mark.parametrize(
    "failure",
    [
        PokeApiUnavailableError("down"),
        PokeApiRateLimitedError("slow down"),
        PokeApiResponseError("garbage"),
    ],
)
def test_uncached_lookup_during_outage_raises_upstream_unavailable(
    catalog: PokemonCatalog,
    repository: SqlitePokemonRepository,
    source: FakeSource,
    failure: PokeApiError,
) -> None:
    source.failure = failure

    with pytest.raises(UpstreamUnavailableError) as excinfo:
        catalog.get("pikachu")
    assert excinfo.value.__cause__ is failure
    assert repository.count() == 0


def test_unknown_pokemon_raises_not_in_catalog(catalog: PokemonCatalog) -> None:
    with pytest.raises(PokemonNotInCatalogError):
        catalog.get("missingno")


def test_offline_catalog_never_calls_upstream(repository: SqlitePokemonRepository) -> None:
    repository.save(PIKACHU)
    catalog = PokemonCatalog(repository)

    assert catalog.get("pikachu") == PIKACHU
    with pytest.raises(PokemonNotInCatalogError):
        catalog.get("charizard")


@pytest.mark.parametrize("identifier", ["", "  ", 0, -3, True])
def test_invalid_identifier_is_rejected_before_any_lookup(
    catalog: PokemonCatalog, source: FakeSource, identifier: str | int
) -> None:
    with pytest.raises(ValueError):
        catalog.get(identifier)
    assert source.calls == []


def test_list_all_returns_stored_pokemon(catalog: PokemonCatalog) -> None:
    catalog.get("pikachu")
    catalog.get("charizard")

    assert catalog.list_all() == [CHARIZARD, PIKACHU]


def test_move_miss_imports_and_hit_is_local(
    catalog: PokemonCatalog, repository: SqlitePokemonRepository, source: FakeSource
) -> None:
    assert catalog.get_move("thunderbolt") == THUNDERBOLT
    assert repository.get_move_by_id(85) == THUNDERBOLT

    source.failure = PokeApiUnavailableError("down")
    assert catalog.get_move(85) == THUNDERBOLT
    assert catalog.get_move(" Thunderbolt ") == THUNDERBOLT
    assert source.move_calls == ["thunderbolt"]


def test_unknown_move_raises_move_not_in_catalog(catalog: PokemonCatalog) -> None:
    with pytest.raises(MoveNotInCatalogError, match="does not exist"):
        catalog.get_move("splashier")


def test_uncached_move_during_outage_raises_upstream_unavailable(
    catalog: PokemonCatalog, source: FakeSource
) -> None:
    source.failure = PokeApiResponseError("unsupported")

    with pytest.raises(UpstreamUnavailableError):
        catalog.get_move("thunderbolt")


def test_offline_move_miss(repository: SqlitePokemonRepository) -> None:
    with pytest.raises(MoveNotInCatalogError, match="not in the local catalog"):
        PokemonCatalog(repository).get_move("thunderbolt")
