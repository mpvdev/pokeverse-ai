from collections.abc import Iterator

import pytest

from pokeverse.catalog import (
    BaseStats,
    DamageClass,
    Move,
    MoveNotInCatalogError,
    Pokemon,
    PokemonCatalog,
    PokemonEntry,
    PokemonIndex,
    PokemonNotInCatalogError,
    PokemonType,
    SqlitePokemonRepository,
    StaticSource,
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


def test_lookup_fetches_from_source_and_syncs_to_sqlite(
    catalog: PokemonCatalog, repository: SqlitePokemonRepository, source: FakeSource
) -> None:
    assert catalog.get("pikachu") == PIKACHU
    assert source.calls == ["pikachu"]
    assert repository.get_by_id(25) == PIKACHU


def test_record_is_fetched_once_per_catalog(catalog: PokemonCatalog, source: FakeSource) -> None:
    catalog.get("pikachu")
    catalog.get("pikachu")
    catalog.get(25)
    catalog.get("  Pikachu ")

    assert source.calls == ["pikachu"]


def test_new_catalog_refetches_even_when_stored(
    repository: SqlitePokemonRepository, source: FakeSource
) -> None:
    repository.save(PIKACHU)

    assert PokemonCatalog(repository, source).get("pikachu") == PIKACHU
    assert PokemonCatalog(repository, source).get("pikachu") == PIKACHU
    assert source.calls == ["pikachu", "pikachu"]


def test_lookup_by_id_is_reused_by_name(catalog: PokemonCatalog, source: FakeSource) -> None:
    assert catalog.get(6) == CHARIZARD
    assert source.calls == [6]
    assert catalog.get("charizard") == CHARIZARD
    assert source.calls == [6]


def test_stored_pokemon_are_not_served_during_outage(
    repository: SqlitePokemonRepository, source: FakeSource
) -> None:
    repository.save(CHARIZARD)
    source.failure = PokeApiUnavailableError("down")

    with pytest.raises(UpstreamUnavailableError):
        PokemonCatalog(repository, source).get("charizard")


@pytest.mark.parametrize(
    "failure",
    [
        PokeApiUnavailableError("down"),
        PokeApiRateLimitedError("slow down"),
        PokeApiResponseError("garbage"),
    ],
)
def test_lookup_during_outage_raises_upstream_unavailable(
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
    with pytest.raises(PokemonNotInCatalogError, match="does not exist"):
        catalog.get("missingno")


@pytest.mark.parametrize("identifier", ["", "  ", 0, -3, True])
def test_invalid_identifier_is_rejected_before_any_lookup(
    catalog: PokemonCatalog, source: FakeSource, identifier: str | int
) -> None:
    with pytest.raises(ValueError):
        catalog.get(identifier)
    assert source.calls == []


def test_index_pages_through_the_source(repository: SqlitePokemonRepository) -> None:
    catalog = PokemonCatalog(repository, StaticSource([PIKACHU, CHARIZARD]))

    first = catalog.index(1)
    second = catalog.index(1, offset=1)

    assert first == PokemonIndex(count=2, results=(PokemonEntry(pokedex_id=6, name="charizard"),))
    assert second.results == (PokemonEntry(pokedex_id=25, name="pikachu"),)
    assert catalog.index(5, offset=2).results == ()


def test_index_during_outage_raises_upstream_unavailable(
    repository: SqlitePokemonRepository,
) -> None:
    class Down:
        def fetch_index(self, limit: int, offset: int) -> PokemonIndex:
            raise PokeApiUnavailableError("down")

    with pytest.raises(UpstreamUnavailableError):
        PokemonCatalog(repository, Down()).index(20)  # type: ignore[arg-type]


def test_move_is_fetched_synced_and_reused_within_catalog(
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


def test_move_during_outage_raises_upstream_unavailable(
    catalog: PokemonCatalog, source: FakeSource
) -> None:
    source.failure = PokeApiResponseError("unsupported")

    with pytest.raises(UpstreamUnavailableError):
        catalog.get_move("thunderbolt")


def test_static_source_reports_unknown_records_as_not_found() -> None:
    source = StaticSource([PIKACHU], [THUNDERBOLT])

    assert source.fetch_pokemon(25) == PIKACHU
    assert source.fetch_move("thunderbolt") == THUNDERBOLT
    with pytest.raises(PokemonNotFoundError):
        source.fetch_pokemon("charizard")
    with pytest.raises(PokemonNotFoundError):
        source.fetch_move(1)
