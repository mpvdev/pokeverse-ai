import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pokeverse.api import CatalogProvider, create_app
from pokeverse.catalog import PokemonCatalog, SqlitePokemonRepository
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.llm import Completion, OutputSchema, Tool, ToolCall

FIXTURES = Path(__file__).parent.parent / "catalog" / "fixtures" / "pokeapi"


@dataclass
class Reply:
    """One scripted model turn: tools to run (for real), then the final text or data."""

    tools: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    data: dict[str, Any] | None = None
    text: str = ""


class FakeChat:
    """Plays scripted replies in order; nested agent calls take the next ones.

    With the script empty, battle decisions and opponent analyses get a valid default reply.
    """

    def __init__(self) -> None:
        self.script: list[Reply | Exception] = []
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        *,
        tools: Sequence[Tool] = (),
        output_schema: OutputSchema | None = None,
        **kwargs: Any,
    ) -> Completion:
        self.calls.append({"prompt": prompt, "schema": output_schema, **kwargs})
        reply = self.script.pop(0) if self.script else default_reply(output_schema)
        if isinstance(reply, Exception):
            raise reply
        by_name = {tool.name: tool for tool in tools}
        calls = tuple(
            ToolCall(name=name, arguments=args, output=by_name[name].handler(**args))
            for name, args in reply.tools
        )
        return Completion(reply.text, "fake-model", "completed", 100, 20, 5, calls, reply.data)


def default_reply(schema: OutputSchema | None) -> Reply:
    assert schema is not None, "FakeChat script is empty"
    properties = schema.schema["properties"]
    if schema.name == "battle_decision":
        return Reply(data={"action": properties["action"]["enum"][0], "reason": "First option."})
    if schema.name == "opponent_analysis":
        foes = properties["threats"]["items"]["properties"]["foe"]["enum"]
        own = properties["counters"]["items"]["properties"]["answer"]["enum"]
        return Reply(
            data={
                "threats": [{"foe": foe, "danger": "high", "reason": "Fast."} for foe in foes],
                "counters": [{"threat": foes[0], "answer": own[0], "reason": "Wins."}],
                "plan": "Lead with our first Pokémon.",
            }
        )
    raise AssertionError(f"no default reply for {schema.name}")


class FakePokeApi:
    """Serves recorded PokéAPI fixtures; records requests and can be switched off."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("connection refused")
        if request.url.path.endswith("/pokemon"):
            return httpx.Response(200, json=self.index(request.url.params))
        resource, name = request.url.path.rstrip("/").split("/")[-2:]
        name = {"25": "pikachu", "6": "charizard", "85": "thunderbolt"}.get(name, name)
        folder = FIXTURES if resource == "pokemon" else FIXTURES / resource
        fixture = folder / f"{name}.json"
        if not fixture.exists():
            return httpx.Response(404, json={"detail": "Not Found"})
        return httpx.Response(200, json=json.loads(fixture.read_text()))

    @staticmethod
    def index(params: httpx.QueryParams) -> dict[str, object]:
        entries = sorted((json.loads(p.read_text())["id"], p.stem) for p in FIXTURES.glob("*.json"))
        offset, limit = int(params["offset"]), int(params["limit"])
        return {
            "count": len(entries),
            "results": [
                {"name": name, "url": f"https://pokeapi.co/api/v2/pokemon/{pokedex_id}/"}
                for pokedex_id, name in entries[offset : offset + limit]
            ],
        }


@pytest.fixture
def pokeapi() -> FakePokeApi:
    return FakePokeApi()


@pytest.fixture
def chat() -> FakeChat:
    return FakeChat()


@pytest.fixture
def catalogs(tmp_path: Path, pokeapi: FakePokeApi) -> CatalogProvider:
    db_path = tmp_path / "catalog.db"

    @contextmanager
    def open_catalog() -> Iterator[PokemonCatalog]:
        transport = httpx.MockTransport(pokeapi.handler)
        with (
            SqlitePokemonRepository(db_path) as repository,
            PokeApiClient(transport=transport) as upstream,
        ):
            yield PokemonCatalog(repository, upstream)

    return open_catalog


def run_now(work: Callable[[], None]) -> None:
    work()


@pytest.fixture
def client(catalogs: CatalogProvider, chat: FakeChat) -> Iterator[TestClient]:
    with TestClient(create_app(catalogs, chats=lambda: chat, runner=run_now)) as test_client:
        yield test_client
