import pytest
from conftest import FakeChat, FakePokeApi, Reply
from fastapi.testclient import TestClient

from pokeverse.api import CatalogProvider, create_app
from pokeverse.llm import LlmAuthError, LlmUnavailableError

PIKACHU_ANSWER = {"answer": "Pikachu is Electric.", "pokemon": ["pikachu"], "confidence": "high"}


def test_research_is_grounded_by_real_tool_calls(client: TestClient, chat: FakeChat) -> None:
    chat.script = [Reply(tools=[("get_pokemon", {"name_or_id": "Pikachu"})], data=PIKACHU_ANSWER)]

    response = client.post("/research", json={"question": "What type is Pikachu?"})

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == {"answer": PIKACHU_ANSWER, "ungrounded": []}
    assert body["usage"]["model"] == "fake-model"
    assert body["usage"]["total_tokens"] == 120
    assert body["usage"]["tool_calls"] == [
        {"name": "get_pokemon", "arguments": {"name_or_id": "Pikachu"}}
    ]
    assert chat.calls[0]["prompt"] == "What type is Pikachu?"


def test_research_reports_claims_without_a_lookup(client: TestClient, chat: FakeChat) -> None:
    chat.script = [Reply(data={**PIKACHU_ANSWER, "pokemon": ["charizard"]})]

    body = client.post("/research", json={"question": "Charizard?"}).json()

    assert body["result"]["ungrounded"] == ["charizard"]


@pytest.mark.parametrize(
    ("reply", "status", "detail"),
    [
        (
            Reply(data={"answer": "x", "pokemon": ["Not A Slug"], "confidence": "high"}),
            502,
            "pokemon.0",
        ),
        (LlmUnavailableError("rate limited"), 503, "rate limited"),
        (LlmAuthError("bad key"), 502, "bad key"),
    ],
)
def test_llm_failures_map_to_status_codes(
    client: TestClient, chat: FakeChat, reply: object, status: int, detail: str
) -> None:
    chat.script = [reply]  # type: ignore[list-item]

    response = client.post("/research", json={"question": "Pikachu?"})

    assert response.status_code == status
    assert detail in response.json()["detail"]


def test_missing_credentials_fail_before_any_work(
    catalogs: CatalogProvider, pokeapi: FakePokeApi
) -> None:
    def no_credentials() -> FakeChat:
        raise LlmAuthError("OPENAI_API_KEY is not set.")

    client = TestClient(create_app(catalogs, chats=no_credentials))

    response = client.post("/research", json={"question": "Pikachu?"})

    assert response.status_code == 502
    assert "OPENAI_API_KEY" in response.json()["detail"]
    assert pokeapi.requests == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/research", {"question": "   "}),
        ("/research", {"question": "x" * 2001}),
        ("/teams/build", {}),
        ("/teams/optimize", {"members": []}),
        ("/teams/optimize", {"members": ["pikachu"], "keep": [25]}),
        ("/advise", {"request": "hi", "optimize": "sometimes"}),
        ("/scout", {"side1": [{"pokemon": "pikachu"}], "side2": []}),
    ],
)
def test_invalid_requests_are_422_before_any_model_call(
    client: TestClient, chat: FakeChat, path: str, body: dict[str, object]
) -> None:
    assert client.post(path, json=body).status_code == 422
    assert chat.calls == []


def test_build_is_rechecked_by_our_code(client: TestClient, chat: FakeChat) -> None:
    chat.script = [
        Reply(
            tools=[("analyze_team", {"names": ["pikachu", "charizard"]})],
            data={
                "members": [
                    {"name": "pikachu", "role": "Fast special attacker"},
                    {"name": "charizard", "role": "Fire coverage"},
                ],
                "summary": "Electric and Fire.",
            },
        )
    ]

    body = client.post("/teams/build", json={"request": "Pikachu and a partner"}).json()

    result = body["result"]
    assert [m["name"] for m in result["proposal"]["members"]] == ["pikachu", "charizard"]
    assert [m["name"] for m in result["analysis"]["team"]["members"]] == ["pikachu", "charizard"]
    assert "vulnerabilities" in result["analysis"]
    assert result["self_checked"] is True
    assert body["usage"]["tool_calls"][0]["name"] == "analyze_team"


def test_build_with_an_invented_pokemon_is_502(client: TestClient, chat: FakeChat) -> None:
    chat.script = [Reply(data={"members": [{"name": "missingno", "role": "x"}], "summary": "s"})]

    response = client.post("/teams/build", json={"request": "anything"})

    assert response.status_code == 502
    assert "does not exist" in response.json()["detail"]


def test_optimize_checks_claims_against_the_type_chart(client: TestClient, chat: FakeChat) -> None:
    chat.script = [
        Reply(
            data={
                "claims": [
                    {"member": "charizard", "attacking_type": "ground", "claimed": "resists"}
                ],
                "swaps": [{"out": "pikachu", "in": "charizard", "reason": "More fire."}],
                "critique": "Ground is a problem.",
            }
        )
    ]

    response = client.post(
        "/teams/optimize",
        json={
            "members": ["pikachu", "charizard"],
            "keep": ["Pikachu"],
            "notes": "Charizard resists Ground.",
        },
    )

    result = response.json()["result"]
    assert result["claims"] == [
        {
            "member": "charizard",
            "attacking_type": "ground",
            "claimed": "resists",
            "actual": "immune",
            "multiplier": 0.0,
            "correct": False,
        }
    ]
    assert result["swaps"][0]["in"] == "charizard"
    assert result["swaps"][0]["accepted"] is False
    assert result["swaps"][0]["verdict"] == "the user asked to keep this member"
    assert [m["name"] for m in result["final"]["team"]["members"]] == ["pikachu", "charizard"]


def test_optimize_with_an_unknown_member_is_404(client: TestClient, chat: FakeChat) -> None:
    assert client.post("/teams/optimize", json={"members": ["missingno"]}).status_code == 404
    assert chat.calls == []


def test_advise_reports_delegations_facts_and_tokens(client: TestClient, chat: FakeChat) -> None:
    chat.script = [
        Reply(
            tools=[("ask_research_agent", {"task": "What type is Pikachu?"})],
            text="Pikachu is an Electric-type.",
        ),
        Reply(tools=[("get_pokemon", {"name_or_id": "pikachu"})], data=PIKACHU_ANSWER),
    ]

    body = client.post("/advise", json={"request": "What type is Pikachu?"}).json()

    result = body["result"]
    assert result["answer"] == "Pikachu is an Electric-type."
    (delegation,) = result["delegations"]
    assert delegation["agent"] == "research"
    assert delegation["output"]["ungrounded"] == []
    assert delegation["tokens"] == 120
    assert [p["name"] for p in result["facts"]["pokemon"]] == ["pikachu"]
    assert result["specialist_tokens"] == 120
    assert result["total_tokens"] == 240
    assert body["usage"]["total_tokens"] == 120


def test_scout_rejects_unsupported_moves_before_any_model_call(
    client: TestClient, chat: FakeChat
) -> None:
    body = client.post(
        "/scout",
        json={
            "side1": [{"pokemon": "pikachu", "moves": ["thunderbolt"]}],
            "side2": [{"pokemon": "charizard", "moves": ["swords-dance"]}],
        },
    )

    assert body.status_code == 422
    assert "not supported in battle" in body.json()["detail"]
    assert chat.calls == []


def test_scout_verifies_counters_and_returns_the_briefing(client: TestClient) -> None:
    body = client.post(
        "/scout",
        json={
            "side1": [{"pokemon": "pikachu", "moves": ["thunderbolt"]}],
            "side2": [{"pokemon": "pikachu", "moves": ["quick-attack"]}],
        },
    ).json()

    result = body["result"]
    assert result["analysis"]["threats"] == [
        {"foe": "foe-0:pikachu", "danger": "high", "reason": "Fast."}
    ]
    assert result["analysis"]["counters"][0]["verified"] is True
    assert "Keep Pikachu for Pikachu" in result["briefing"]
