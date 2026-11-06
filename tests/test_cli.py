import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from pokeverse import cli
from pokeverse.agents import POKEDEX_ANSWER_SCHEMA, TEAM_PROPOSAL_SCHEMA
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.cli import (
    EXIT_AUTH,
    EXIT_EVAL_FAILED,
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


def test_team_prints_analysis(db: str, upstream: Upstream) -> None:
    result = invoke(db, "team", "Pikachu", "charizard")

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "Team: Pikachu, Charizard"
    assert lines[1] == "Vulnerable to: none"
    assert lines[2].startswith("Unresisted attack types: normal, water")
    assert lines[3].startswith("Offensive gaps (STAB): normal, fire")


def test_team_json(db: str, upstream: Upstream) -> None:
    result = invoke(db, "team", "25", "6", "--json")

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [member["name"] for member in data["team"]["members"]] == ["pikachu", "charizard"]
    assert data["vulnerabilities"] == []


def test_team_allows_repeated_pokemon(db: str, upstream: Upstream) -> None:
    result = invoke(db, "team", "pikachu", "Pikachu", "--json")

    assert result.exit_code == 0
    ground = next(
        e for e in json.loads(result.stdout)["vulnerabilities"] if e["attacking_type"] == "ground"
    )
    assert ground["weak"] == ["pikachu", "pikachu"]
    assert upstream.requests == ["/api/v2/pokemon/pikachu"]


def test_team_unknown_pokemon_exits_not_found(db: str, upstream: Upstream) -> None:
    result = invoke(db, "team", "pikachu", "missingno")

    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stdout == ""
    assert "does not exist" in result.stderr


def test_team_size_is_checked_before_any_lookup(db: str, upstream: Upstream) -> None:
    result = invoke(db, "team", *["pikachu"] * 7)

    assert result.exit_code == EXIT_INVALID_INPUT
    assert "at most 6" in result.stderr
    assert upstream.requests == []


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
    """Stands in for OpenAIChat in CLI tests; records calls, runs tools, can raise."""

    calls: list[dict[str, object]] = []
    error: Exception | None = None
    data: dict[str, Any] | None = None
    analyzed: list[str] | None = None

    def __init__(self, settings: object = None) -> None:
        pass

    def complete(self, prompt: str, **kwargs: Any):
        from pokeverse.llm import Completion, ToolCall

        FakeChat.calls.append({"prompt": prompt, **kwargs})
        if FakeChat.error is not None:
            raise FakeChat.error
        tool_calls = []
        for tool in kwargs.get("tools", ()):
            arguments = FakeChat.arguments_for(tool)
            tool_calls.append(ToolCall(tool.name, arguments, tool.handler(**arguments)))
        data = FakeChat.data if kwargs.get("output_schema") else None
        return Completion(
            "Pikachu is Electric-type.",
            "fake-model",
            "end_turn",
            10,
            5,
            42,
            tuple(tool_calls),
            data,
        )

    @staticmethod
    def arguments_for(tool: Any) -> dict[str, Any]:
        if "name_or_id" in tool.parameters["properties"]:
            return {"name_or_id": "Pikachu"}
        if FakeChat.analyzed is not None:
            return {"names": FakeChat.analyzed}
        return {"names": [m["name"] for m in (FakeChat.data or {}).get("members", [])]}


@pytest.fixture
def fake_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, upstream: Upstream
) -> type[FakeChat]:
    FakeChat.calls = []
    FakeChat.error = None
    FakeChat.data = None
    FakeChat.analyzed = None
    monkeypatch.setattr(cli, "OpenAIChat", FakeChat)
    monkeypatch.setenv("POKEVERSE_DB", str(tmp_path / "ask.db"))
    return FakeChat


def test_ask_prints_answer(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(app, ["ask", "What type is Pikachu?"])

    assert result.exit_code == 0
    assert result.stdout == "Pikachu is Electric-type.\n"
    assert result.stderr == ""
    (call,) = fake_chat.calls
    assert call["prompt"] == "What type is Pikachu?"
    assert call["system"] == cli.DEFAULT_SYSTEM_PROMPT
    assert call["output_schema"] is None


def test_ask_json_prints_validated_answer(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = {
        "answer": "Pikachu is Electric-type.",
        "pokemon": ["pikachu"],
        "confidence": "high",
    }

    result = runner.invoke(app, ["ask", "What type is Pikachu?", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == fake_chat.data
    assert fake_chat.calls[0]["output_schema"] is POKEDEX_ANSWER_SCHEMA


def test_ask_json_rejects_invalid_model_reply(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = {"answer": "Electric.", "pokemon": ["Pikachu"], "confidence": "high"}

    result = runner.invoke(app, ["ask", "What type is Pikachu?", "--json"])

    assert result.exit_code == EXIT_INVALID_INPUT
    assert result.stdout == ""
    assert "failed validation" in result.stderr


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


def test_ask_gives_model_the_catalog_tools(fake_chat: type[FakeChat], upstream: Upstream) -> None:
    result = runner.invoke(app, ["ask", "What type is Pikachu?", "--usage"])

    assert result.exit_code == 0
    tools = fake_chat.calls[0]["tools"]
    assert [tool.name for tool in tools] == ["get_pokemon", "get_type_matchups"]  # type: ignore[attr-defined]
    # The second lookup is served from the local catalog.
    assert upstream.requests == ["/api/v2/pokemon/pikachu"]
    assert '[tool] get_pokemon({"name_or_id": "Pikachu"}) -> {"pokedex_id": 25' in result.stderr
    assert '"weak_to": {"ground": 2.0}' in result.stderr


def test_ask_without_tools(fake_chat: type[FakeChat], upstream: Upstream) -> None:
    result = runner.invoke(app, ["ask", "hi", "--no-tools"])

    assert result.exit_code == 0
    assert fake_chat.calls[0]["tools"] == ()
    assert upstream.requests == []


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
        "auth": LlmAuthError("invalid API key"),
        "unavailable": LlmUnavailableError("throttled"),
        "request": LlmRequestError("bad model"),
        "value": ValueError("prompt must not be empty"),
    }[error]

    result = runner.invoke(app, ["ask", "hi"])

    assert result.exit_code == code
    assert result.stdout == ""
    assert result.stderr.startswith("Error:")


PIKACHU_ANSWER = {
    "answer": "Pikachu is Electric-type.",
    "pokemon": ["pikachu"],
    "confidence": "high",
}


def test_research_prints_grounded_answer(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = PIKACHU_ANSWER

    result = runner.invoke(app, ["research", "What type is Pikachu?"])

    assert result.exit_code == 0
    assert result.stdout == "Pikachu is Electric-type.\n"
    assert "confidence: high" in result.stderr
    assert "Warning" not in result.stderr
    assert fake_chat.calls[0]["output_schema"] is POKEDEX_ANSWER_SCHEMA


def test_research_json_flags_ungrounded_pokemon(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = {**PIKACHU_ANSWER, "pokemon": ["pikachu", "raichu"]}

    result = runner.invoke(app, ["research", "Pikachu vs Raichu?", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ungrounded"] == ["raichu"]
    assert "not verified against the catalog: raichu" in result.stderr


def test_eval_passing_case(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = PIKACHU_ANSWER

    result = runner.invoke(app, ["eval", "--case", "pikachu-type"])

    assert result.exit_code == 0
    assert result.stdout.startswith("PASS pikachu-type")
    assert "1/1 passed | tool use correct 1/1" in result.stdout


def test_eval_failing_case_exits_nonzero(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = PIKACHU_ANSWER

    result = runner.invoke(app, ["eval", "--case", "off-topic"])

    assert result.exit_code == EXIT_EVAL_FAILED
    assert "FAIL off-topic" in result.stdout
    assert "expected lookup=False" in result.stdout


def test_eval_rejects_unknown_case(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(app, ["eval", "--case", "nope"])

    assert result.exit_code == EXIT_INVALID_INPUT
    assert "unknown case" in result.stderr
    assert fake_chat.calls == []


TEAM_PROPOSAL = {
    "members": [
        {"name": "pikachu", "role": "fast electric attacker"},
        {"name": "charizard", "role": "fire coverage"},
    ],
    "summary": "Pikachu leads; Charizard handles Ground threats.",
}


def test_build_prints_team_summary_and_our_analysis(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = TEAM_PROPOSAL

    result = runner.invoke(app, ["build", "A team around Pikachu"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["Pikachu", "electric", "fast", "electric", "attacker"]
    assert lines[1].split()[:2] == ["Charizard", "fire/flying"]
    assert "Pikachu leads; Charizard handles Ground threats." in lines
    assert "Vulnerable to: none" in lines
    assert result.stderr == ""
    assert fake_chat.calls[0]["output_schema"] is TEAM_PROPOSAL_SCHEMA


def test_build_json(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = TEAM_PROPOSAL

    result = runner.invoke(app, ["build", "A team around Pikachu", "--json"])

    data = json.loads(result.stdout)
    assert data["members"] == TEAM_PROPOSAL["members"]
    assert data["self_checked"] is True
    assert data["analysis"]["vulnerabilities"] == []
    assert "exposures" not in data["analysis"]


def test_build_warns_when_final_team_was_not_analyzed(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = TEAM_PROPOSAL
    fake_chat.analyzed = ["pikachu"]

    result = runner.invoke(app, ["build", "A team around Pikachu"])

    assert result.exit_code == 0
    assert "did not analyze this exact team" in result.stderr


def test_build_rejects_invented_pokemon(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = {**TEAM_PROPOSAL, "members": [{"name": "pikablu", "role": "x"}]}
    fake_chat.analyzed = ["pikachu"]

    result = runner.invoke(app, ["build", "A team around Pikachu"])

    assert result.exit_code == EXIT_INVALID_INPUT
    assert "does not exist" in result.stderr


OPTIMIZER_REPLY = {
    "claims": [{"member": "charizard", "attacking_type": "rock", "claimed": "resists"}],
    "swaps": [{"out": "pikachu", "in": "charizard", "reason": "Ground immunity"}],
    "critique": "Two Pikachu share a Ground weakness.",
}


def test_optimize_applies_improving_swap_and_flags_wrong_claim(
    fake_chat: type[FakeChat],
) -> None:
    fake_chat.data = OPTIMIZER_REPLY

    result = runner.invoke(app, ["optimize", "pikachu", "pikachu", "--notes", "x"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].startswith("Before: pikachu, pikachu")
    assert lines[1].startswith("  ACCEPTED pikachu -> charizard: Ground immunity [improved")
    assert lines[2].startswith("After:  charizard, pikachu")
    assert "Vulnerable to: none" in lines
    assert "  WRONG charizard vs rock: claimed resists, actually weak (4x)" in lines
    assert lines[-1] == "Two Pikachu share a Ground weakness."


def test_optimize_respects_keep(fake_chat: type[FakeChat]) -> None:
    fake_chat.data = OPTIMIZER_REPLY

    result = runner.invoke(app, ["optimize", "pikachu", "pikachu", "--keep", "Pikachu", "--json"])

    data = json.loads(result.stdout)
    assert data["final_members"] == ["pikachu", "pikachu"]
    assert data["swaps"][0]["accepted"] is False
    assert "keep this member" in data["swaps"][0]["verdict"]


def test_optimize_unknown_member_exits_not_found(fake_chat: type[FakeChat]) -> None:
    result = runner.invoke(app, ["optimize", "pikachu", "missingno"])

    assert result.exit_code == EXIT_NOT_FOUND
    assert fake_chat.calls == []


def canned_supervisor_result() -> Any:
    from pokeverse.agents import Delegation, SupervisorResult
    from pokeverse.llm import Completion

    research = Completion("", "fake", "completed", 30, 10, 5)
    return SupervisorResult(
        answer="Pikachu is Electric-type.",
        delegations=(
            Delegation("research", "What type is Pikachu?", {"answer": "Electric"}, None, research),
            Delegation("team_builder", "Team around Pikachu", error="Model reply failed"),
        ),
        completion=Completion("Pikachu is Electric-type.", "fake-model", "completed", 100, 20, 9),
    )


@pytest.fixture
def fake_supervisor(monkeypatch: pytest.MonkeyPatch, fake_chat: type[FakeChat]) -> list[str]:
    from pokeverse.agents.supervisor import OPTIMIZE_MODES

    requests: list[str] = []

    class FakeSupervisor:
        def __init__(self, chat: object, catalog: object, *, optimize: str) -> None:
            if optimize not in OPTIMIZE_MODES:
                raise ValueError(f"optimize must be one of {', '.join(OPTIMIZE_MODES)}")
            self.optimize = optimize

        def run(self, request: str) -> Any:
            requests.append(f"{request} [{self.optimize}]")
            return canned_supervisor_result()

    monkeypatch.setattr(cli, "Supervisor", FakeSupervisor)
    return requests


def test_advise_passes_optimize_mode(fake_supervisor: list[str]) -> None:
    runner.invoke(app, ["advise", "q", "--optimize", "never"])

    assert fake_supervisor == ["q [never]"]


def test_advise_rejects_unknown_optimize_mode(fake_supervisor: list[str]) -> None:
    result = runner.invoke(app, ["advise", "q", "--optimize", "sometimes"])

    assert result.exit_code == EXIT_INVALID_INPUT
    assert "never, auto, always" in result.stderr
    assert fake_supervisor == []


def test_advise_prints_answer(fake_supervisor: list[str]) -> None:
    result = runner.invoke(app, ["advise", "What type is Pikachu?"])

    assert result.exit_code == 0
    assert result.stdout == "Pikachu is Electric-type.\n"
    assert result.stderr == ""
    assert fake_supervisor == ["What type is Pikachu? [auto]"]


def test_advise_usage_shows_delegations_and_token_split(fake_supervisor: list[str]) -> None:
    result = runner.invoke(app, ["advise", "q", "--usage"])

    lines = result.stderr.splitlines()
    assert lines[0] == "[delegate] research: 'What type is Pikachu?' -> ok (40 tokens)"
    assert lines[1].startswith("[delegate] team_builder: 'Team around Pikachu' -> error:")
    assert "supervisor=120 specialists=40 total=160" in lines[2]


def test_advise_json(fake_supervisor: list[str]) -> None:
    result = runner.invoke(app, ["advise", "q", "--json"])

    data = json.loads(result.stdout)
    assert data["answer"] == "Pikachu is Electric-type."
    assert [d["agent"] for d in data["delegations"]] == ["research", "team_builder"]
    assert data["usage"]["total_tokens"] == 160


@pytest.fixture
def fake_compare(monkeypatch: pytest.MonkeyPatch, fake_chat: type[FakeChat]) -> list[tuple]:
    from pokeverse.evals.compare import RunOutcome

    calls: list[tuple] = []

    def compare_case(system: str, case: Any, chat: object, catalog: object) -> RunOutcome:
        calls.append((case.id, system))
        failures = () if system == "multi" else ("nobody resists ice",)
        return RunOutcome(case, system, failures, tokens=1000, latency_ms=2000)

    monkeypatch.setattr(cli, "compare_case", compare_case)
    return calls


def test_compare_runs_selected_cases_and_systems(fake_compare: list[tuple]) -> None:
    result = runner.invoke(
        app,
        ["compare", "--case", "gengar-fact", "--system", "multi", "--system", "single"],
    )

    assert result.exit_code == 0
    assert fake_compare == [("gengar-fact", "single"), ("gengar-fact", "multi")]
    lines = result.stdout.splitlines()
    assert lines[0].startswith(f"FAIL {'gengar-fact':<14} single")
    assert lines[1] == "     - nobody resists ice"
    assert lines[2].startswith(f"PASS {'gengar-fact':<14} multi")
    assert "single     passed 0/1 | tokens 1000 (avg 1000) | avg latency 2.0s" in lines
    assert "multi      passed 1/1 | tokens 1000 (avg 1000) | avg latency 2.0s" in lines


def test_compare_json(fake_compare: list[tuple]) -> None:
    result = runner.invoke(app, ["compare", "--case", "fire-only", "--json"])

    data = json.loads(result.stdout)
    assert [run["system"] for run in data["runs"]] == ["single", "multi", "multi+auto", "multi+opt"]
    assert [row["passed"] for row in data["summary"]] == [0, 1, 0, 0]
    assert data["aborted"] is None
    assert "PASS fire-only" in result.stderr


def test_compare_keeps_partial_results_when_aborted(
    monkeypatch: pytest.MonkeyPatch, fake_compare: list[tuple]
) -> None:
    from pokeverse.llm import LlmUnavailableError

    first = cli.compare_case

    def flaky(system: str, case: Any, chat: object, catalog: object) -> Any:
        if system == "multi":
            raise LlmUnavailableError("rate limited")
        return first(system, case, chat, catalog)

    monkeypatch.setattr(cli, "compare_case", flaky)

    result = runner.invoke(app, ["compare", "--case", "fire-only", "--json"])

    assert result.exit_code == EXIT_UPSTREAM_UNAVAILABLE
    data = json.loads(result.stdout)
    assert [run["system"] for run in data["runs"]] == ["single"]
    assert data["aborted"] == "rate limited"
    assert "Error: rate limited" in result.stderr


def test_compare_rejects_unknown_case_or_system(fake_compare: list[tuple]) -> None:
    result = runner.invoke(app, ["compare", "--case", "nope", "--system", "solo"])

    assert result.exit_code == EXIT_INVALID_INPUT
    assert "['nope', 'solo']" in result.stderr
    assert fake_compare == []
