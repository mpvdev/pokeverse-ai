import json
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from pokeverse import cli
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.cli import (
    EXIT_AUTH,
    EXIT_INVALID_INPUT,
    EXIT_NOT_FOUND,
    EXIT_UPSTREAM_UNAVAILABLE,
    app,
    default_db_path,
)

FIXTURES = Path(__file__).parent / "catalog" / "fixtures" / "pokeapi"

runner = CliRunner()


class Upstream:
    """Fake PokéAPI served from recorded fixtures; can be switched off."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("connection refused")
        name = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        name = {"25": "pikachu", "6": "charizard"}.get(name, name)
        fixture = FIXTURES / f"{name}.json"
        if not fixture.exists():
            return httpx.Response(404, json={"status": 404, "message": "Not Found"})
        return httpx.Response(200, json=json.loads(fixture.read_text()))


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    monkeypatch.setattr(
        cli, "PokeApiClient", lambda: PokeApiClient(transport=httpx.MockTransport(fake.handler))
    )
    return fake


@pytest.fixture
def db(tmp_path: Path) -> str:
    return str(tmp_path / "catalog.db")


def invoke(db: str, *args: str):
    return runner.invoke(app, ["--db", db, *args])


def test_cli_prints_welcome_message() -> None:
    result = runner.invoke(app)

    assert result.exit_code == 0
    assert result.stdout == "Welcome to PokéVerse AI\n"


def test_cli_reports_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"{version('pokeverse-ai')}\n"


def test_pokemon_lookup_prints_summary(db: str, upstream: Upstream) -> None:
    result = invoke(db, "pokemon", "Charizard")

    assert result.exit_code == 0
    assert result.stdout == "#0006 Charizard — Fire / Flying\n"


def test_pokemon_lookup_by_id_as_json(db: str, upstream: Upstream) -> None:
    result = invoke(db, "pokemon", "25", "--json")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "pokedex_id": 25,
        "name": "pikachu",
        "types": ["electric"],
    }


def test_second_lookup_is_served_locally(db: str, upstream: Upstream) -> None:
    invoke(db, "pokemon", "pikachu")
    upstream.down = True

    result = invoke(db, "pokemon", "pikachu")

    assert result.exit_code == 0
    assert upstream.requests == ["/api/v2/pokemon/pikachu"]


def test_offline_lookup_never_calls_upstream(db: str, upstream: Upstream) -> None:
    result = invoke(db, "pokemon", "pikachu", "--offline")

    assert result.exit_code == EXIT_NOT_FOUND
    assert "not in the local catalog" in result.stderr
    assert upstream.requests == []


def test_unknown_pokemon_exits_not_found(db: str, upstream: Upstream) -> None:
    result = invoke(db, "pokemon", "missingno")

    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stdout == ""
    assert result.stderr.startswith("Error:")


def test_upstream_outage_exits_unavailable(db: str, upstream: Upstream) -> None:
    upstream.down = True

    result = invoke(db, "pokemon", "pikachu")

    assert result.exit_code == EXIT_UPSTREAM_UNAVAILABLE
    assert result.stdout == ""
    assert "upstream failed" in result.stderr


@pytest.mark.parametrize("identifier", ["", "   ", "0"])
def test_invalid_identifier_exits_invalid_input(
    db: str, upstream: Upstream, identifier: str
) -> None:
    result = invoke(db, "pokemon", identifier)

    assert result.exit_code == EXIT_INVALID_INPUT
    assert upstream.requests == []


def test_list_empty_catalog(db: str) -> None:
    result = invoke(db, "list")

    assert result.exit_code == 0
    assert "empty" in result.stdout


def test_list_shows_stored_pokemon_in_pokedex_order(db: str, upstream: Upstream) -> None:
    invoke(db, "pokemon", "pikachu")
    invoke(db, "pokemon", "charizard")
    upstream.down = True

    text = invoke(db, "list")
    as_json = invoke(db, "list", "--json")

    assert text.stdout == "#0006 Charizard — Fire / Flying\n#0025 Pikachu — Electric\n"
    assert [entry["name"] for entry in json.loads(as_json.stdout)] == ["charizard", "pikachu"]


def test_db_path_can_come_from_environment(tmp_path: Path, upstream: Upstream) -> None:
    db_path = tmp_path / "from-env.db"

    result = runner.invoke(app, ["pokemon", "pikachu"], env={"POKEVERSE_DB": str(db_path)})

    assert result.exit_code == 0
    assert db_path.exists()


def test_default_db_path_respects_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert default_db_path() == tmp_path / "pokeverse" / "catalog.db"


def test_default_db_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert default_db_path() == Path.home() / ".local" / "share" / "pokeverse" / "catalog.db"


class FakeChat:
    """Stands in for BedrockChat in CLI tests; records calls, can raise."""

    calls: list[dict[str, object]] = []
    error: Exception | None = None

    def __init__(self, settings: object = None) -> None:
        pass

    def complete(self, prompt: str, **kwargs: object):
        from pokeverse.llm import Completion

        FakeChat.calls.append({"prompt": prompt, **kwargs})
        if FakeChat.error is not None:
            raise FakeChat.error
        return Completion("Pikachu is Electric-type.", "fake-model", "end_turn", 10, 5, 42)


@pytest.fixture
def fake_chat(monkeypatch: pytest.MonkeyPatch) -> type[FakeChat]:
    FakeChat.calls = []
    FakeChat.error = None
    monkeypatch.setattr(cli, "BedrockChat", FakeChat)
    return FakeChat


def test_ask_prints_answer(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(app, ["ask", "What type is Pikachu?"])

    assert result.exit_code == 0
    assert result.stdout == "Pikachu is Electric-type.\n"
    assert result.stderr == ""
    (call,) = fake_chat.calls
    assert call["prompt"] == "What type is Pikachu?"
    assert call["system"] == cli.DEFAULT_SYSTEM_PROMPT


def test_ask_passes_options(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(
        app, ["ask", "hi", "--system", "Be brief.", "-t", "0.9", "--max-tokens", "20"]
    )

    assert result.exit_code == 0
    (call,) = fake_chat.calls
    assert (call["system"], call["temperature"], call["max_tokens"]) == ("Be brief.", 0.9, 20)


def test_ask_usage_goes_to_stderr(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(app, ["ask", "hi", "--usage"])

    assert result.stdout == "Pikachu is Electric-type.\n"
    assert "tokens in=10 out=5 total=15" in result.stderr
    assert "latency=42ms" in result.stderr


def test_ask_rejects_out_of_range_temperature(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(app, ["ask", "hi", "-t", "1.5"])

    assert result.exit_code == 2
    assert fake_chat.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("auth", EXIT_AUTH),
        ("unavailable", EXIT_UPSTREAM_UNAVAILABLE),
        ("request", EXIT_INVALID_INPUT),
        ("value", EXIT_INVALID_INPUT),
    ],
)
def test_ask_maps_errors_to_exit_codes(fake_chat: type[FakeChat], error: str, code: int) -> None:
    from pokeverse.llm import LlmAuthError, LlmRequestError, LlmUnavailableError

    fake_chat.error = {
        "auth": LlmAuthError("expired, try: aws sso login"),
        "unavailable": LlmUnavailableError("throttled"),
        "request": LlmRequestError("bad model"),
        "value": ValueError("prompt must not be empty"),
    }[error]

    result = runner.invoke(app, ["ask", "hi"])

    assert result.exit_code == code
    assert result.stdout == ""
    assert result.stderr.startswith("Error:")
