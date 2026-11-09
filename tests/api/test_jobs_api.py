import pytest
from conftest import FakeChat, FakePokeApi, Reply
from fastapi.testclient import TestClient

from pokeverse.api import CatalogProvider, create_app, jobs
from pokeverse.evals.battles import BattleScenario
from pokeverse.llm import LlmAuthError, LlmUnavailableError

SIDES = {
    "side1": [{"pokemon": "pikachu", "moves": ["thunderbolt", "surf"]}],
    "side2": [{"pokemon": "pikachu", "moves": ["quick-attack"]}],
}


def submit(client: TestClient, path: str, body: dict[str, object]) -> dict[str, object]:
    response = client.post(path, json=body)
    assert response.status_code == 202, response.text
    job = response.json()
    assert response.headers["Location"] == f"/jobs/{job['id']}"
    return client.get(f"/jobs/{job['id']}").json()


@pytest.fixture
def pikachu_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = BattleScenario(
        id="bulk", side1=("pikachu",), side2=("pikachu",), description="Mirror."
    )
    monkeypatch.setattr(jobs, "SCENARIOS", {"bulk": scenario})


def test_code_battles_summed_over_runs(client: TestClient, chat: FakeChat) -> None:
    job = submit(client, "/jobs/battles", {**SIDES, "runs": 3, "events": False})

    assert job["kind"] == "battles"
    assert job["status"] == "succeeded"
    assert job["error"] is None
    result = job["result"]
    assert sum(result["wins"]) + result["draws"] == 3
    assert [battle["seed"] for battle in result["battles"]] == [0, 1, 2]
    assert all(battle["events"] is None for battle in result["battles"])
    assert result["teams"][0] == [{"pokemon": "pikachu", "moves": ["thunderbolt", "surf"]}]
    assert len(job["progress"]) == 3
    assert job["started_at"] <= job["finished_at"]
    assert chat.calls == []


def test_agent_battle_with_scouting(client: TestClient, chat: FakeChat) -> None:
    job = submit(client, "/jobs/battles", {**SIDES, "player1": "agent", "seed": 4})

    result = job["result"]
    assert job["status"] == "succeeded"
    assert result["players"] == ["agent", "greedy"]
    assert result["analyses"]["1"]["threats"][0]["foe"] == "foe-0:pikachu"
    assert result["analysis_tokens"] == 120
    (battle,) = result["battles"]
    assert battle["decisions"][0]["action"].startswith("move-0:")
    assert battle["agent_tokens"] == 120 * len([d for d in battle["decisions"] if d["tokens"]])
    assert battle["events"][0]["kind"] == "switch"
    assert job["progress"][0] == "side 1 scouted the opponent"


def test_failures_inside_a_job_are_classified(client: TestClient) -> None:
    job = submit(client, "/jobs/battles", {**SIDES, "side2": [{"pokemon": "missingno"}]})

    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"]["kind"] == "not_found"
    assert "missingno" in job["error"]["message"]


def test_llm_outage_inside_a_job(client: TestClient, chat: FakeChat) -> None:
    chat.script = [LlmUnavailableError("overloaded")]

    job = submit(client, "/jobs/battles", {**SIDES, "player1": "agent"})

    assert job["error"] == {"kind": "llm_unavailable", "message": "overloaded"}


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/jobs/nope").status_code == 404


@pytest.mark.parametrize(
    ("path", "body", "loc"),
    [
        ("/jobs/battles", {**SIDES, "runs": 0}, ["body", "runs"]),
        ("/jobs/battles", {**SIDES, "player1": "human"}, ["body", "player1"]),
        ("/jobs/battle-evals", {"systems": ["chess"]}, ["body", "systems", 0]),
        ("/jobs/battle-evals", {"scenarios": ["nowhere"]}, ["body", "scenarios", 0]),
        ("/jobs/battle-feedback", {"train": 0}, ["body", "train"]),
        ("/jobs/research-evals", {"cases": ["no-such-case"]}, ["body", "cases", 0]),
        ("/jobs/compare", {"systems": []}, ["body", "systems"]),
    ],
)
def test_invalid_job_requests_are_422_and_start_nothing(
    client: TestClient, pokeapi: FakePokeApi, path: str, body: dict[str, object], loc: list[object]
) -> None:
    response = client.post(path, json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == loc
    assert pokeapi.requests == []


def test_llm_jobs_need_credentials_at_submission(catalogs: CatalogProvider) -> None:
    def no_credentials() -> FakeChat:
        raise LlmAuthError("OPENAI_API_KEY is not set.")

    started: list[object] = []
    client = TestClient(create_app(catalogs, chats=no_credentials, runner=started.append))

    response = client.post("/jobs/battles", json={**SIDES, "player1": "agent"})

    assert response.status_code == 502
    assert started == []
    assert client.post("/jobs/battles", json=SIDES).status_code == 202


def test_jobs_wait_for_the_runner(catalogs: CatalogProvider, chat: FakeChat) -> None:
    started: list[object] = []
    client = TestClient(create_app(catalogs, chats=lambda: chat, runner=started.append))

    job = client.post("/jobs/battles", json=SIDES).json()

    assert job["status"] == "queued"
    assert job["started_at"] is None
    (work,) = started
    work()
    assert client.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"


def test_battle_eval_job(client: TestClient, pikachu_scenario: None) -> None:
    job = submit(
        client, "/jobs/battle-evals", {"scenarios": ["bulk"], "systems": ["greedy"], "seeds": 4}
    )

    assert job["status"] == "succeeded"
    assert job["result"]["seeds"] == [0, 1, 2, 3]
    (report,) = job["result"]["scenarios"]["bulk"]
    assert report["system"] == "greedy"
    assert report["battles"] == 4
    assert job["progress"]


def test_battle_feedback_job(client: TestClient, pikachu_scenario: None) -> None:
    job = submit(client, "/jobs/battle-feedback", {"train": 2, "test": 2, "seed_start": 10})

    result = job["result"]
    assert job["status"] == "succeeded"
    assert result["train_seeds"] == [10, 11]
    assert result["test_seeds"] == [12, 13]
    assert result["training"]["system"] == "agent"


def test_research_eval_job_reports_failed_cases_as_results(
    client: TestClient, chat: FakeChat
) -> None:
    chat.script = [
        Reply(
            tools=[("get_pokemon", {"name_or_id": "pikachu"})],
            data={"answer": "Pikachu is Electric.", "pokemon": ["pikachu"], "confidence": "high"},
        )
    ]

    job = submit(client, "/jobs/research-evals", {"cases": ["pikachu-type"]})

    result = job["result"]
    assert job["status"] == "succeeded"
    assert (result["passed"], result["total"], result["tool_use_correct"]) == (1, 1, 1)
    assert result["results"][0]["case"] == "pikachu-type"
    assert result["tokens"] == 120
    assert job["progress"] == ["PASS pikachu-type"]


def test_compare_job(client: TestClient, chat: FakeChat) -> None:
    chat.script = [Reply(data={"answer": "No team.", "team": []})]

    job = submit(client, "/jobs/compare", {"cases": ["garchomp-team"], "systems": ["single"]})

    result = job["result"]
    assert job["status"] == "succeeded"
    (run,) = result["runs"]
    assert (run["case"], run["system"], run["passed"]) == ("garchomp-team", "single", False)
    assert result["summary"] == [{"system": "single", "passed": 0, "runs": 1, "tokens": 120}]
    assert result["aborted"] is None


def test_compare_keeps_finished_runs_when_the_llm_goes_down(
    client: TestClient, chat: FakeChat
) -> None:
    chat.script = [
        Reply(data={"answer": "No team.", "team": []}),
        LlmUnavailableError("overloaded"),
    ]

    job = submit(
        client, "/jobs/compare", {"cases": ["garchomp-team", "fire-only"], "systems": ["single"]}
    )

    result = job["result"]
    assert job["status"] == "succeeded"
    assert [run["case"] for run in result["runs"]] == ["garchomp-team"]
    assert result["aborted"] == "llm_unavailable: overloaded"
