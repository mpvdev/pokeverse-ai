import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pokeverse.api import CatalogProvider, create_app
from pokeverse.catalog import PokemonCatalog, SqlitePokemonRepository
from pokeverse.catalog.pokeapi import PokeApiClient

FIXTURES = Path(__file__).parent.parent / "catalog" / "fixtures" / "pokeapi"


class FakePokeApi:
    """Serves recorded PokéAPI fixtures; records requests and can be switched off."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("connection refused")
        resource, name = request.url.path.rstrip("/").split("/")[-2:]
        name = {"25": "pikachu", "6": "charizard", "85": "thunderbolt"}.get(name, name)
        folder = FIXTURES if resource == "pokemon" else FIXTURES / resource
        fixture = folder / f"{name}.json"
        if not fixture.exists():
            return httpx.Response(404, json={"detail": "Not Found"})
        return httpx.Response(200, json=json.loads(fixture.read_text()))


@pytest.fixture
def pokeapi() -> FakePokeApi:
    return FakePokeApi()


@pytest.fixture
def client(tmp_path: Path, pokeapi: FakePokeApi) -> Iterator[TestClient]:
    db_path = tmp_path / "catalog.db"

    @contextmanager
    def catalogs(offline: bool) -> Iterator[PokemonCatalog]:
        with SqlitePokemonRepository(db_path) as repository:
            if offline:
                yield PokemonCatalog(repository)
                return
            transport = httpx.MockTransport(pokeapi.handler)
            with PokeApiClient(transport=transport) as upstream:
                yield PokemonCatalog(repository, upstream)

    provider: CatalogProvider = catalogs
    with TestClient(create_app(provider)) as test_client:
        yield test_client
