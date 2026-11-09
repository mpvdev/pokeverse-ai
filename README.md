# PokéVerse AI

A learning-oriented multi-agent AI platform inspired by Pokémon, built backend-first as a Python REST API (FastAPI).

**Status:** Phase 3.5 (REST API) complete. Next: Phase 4 — Persistent Pokémon World. See [docs/PROGRESS.md](docs/PROGRESS.md).

## What it does

- **Pokémon catalog** — looks Pokémon and moves up from [PokéAPI](https://pokeapi.co/) on every request (types, base stats, learnsets) and mirrors what it fetched to SQLite.
- **Research Agent** — answers Pokémon questions with tool calling and validated, structured answers; a grounding check flags any Pokémon the answer names but never looked up.
- **Type matchups and team analysis** — deterministic code (no LLM): the Gen 6+ type chart, weaknesses, resistances, team vulnerabilities and coverage gaps.
- **Team building** — a Team Composition Agent builds teams from plain-language requests; a Team Optimization Agent fact-checks type claims and proposes swaps, which code keeps only if the team measurably improves.
- **Supervisor** — `/advise` routes any request to the right specialist agents and hands verified facts between them.
- **Battles** — a deterministic, seeded battle engine (level-50 stats, Gen 6+ damage formula, simplified singles); default movesets; random and greedy players; a Battle Strategy Agent that chooses moves from code-computed facts; an Opponent Analysis Agent whose counters are verified against one-on-one matchups.
- **Evaluation** — fixed test suites scored by code, run as background jobs: research questions, single- vs multi-agent team building, and battle win rates with 95% confidence intervals, mistakes detected by code, and a train/test feedback experiment.

Design principle: the LLM handles judgement and language; facts and rules (types, matchups, damage, team scoring, battle legality) are plain, tested code, and model output is always re-checked before it is shown or acted on.

## Requirements

- Python 3.15 and [uv](https://docs.astral.sh/uv/)
- An OpenAI API key for the agent endpoints (temporary provider; Amazon Bedrock is the planned AWS target)

## Setup

```bash
uv sync
echo 'OPENAI_API_KEY=sk-...' > .env
```

`.env` is git-ignored and read when the server starts (real environment variables win). Optional settings: `POKEVERSE_MODEL_ID` (default `gpt-6-luna`), `POKEVERSE_REASONING_EFFORT` (default `none`), `POKEVERSE_DB` (default `~/.local/share/pokeverse/catalog.db`).

## Running the API

```bash
uv run fastapi dev
```

The server listens on http://127.0.0.1:8000 only; interactive documentation for every endpoint is at http://127.0.0.1:8000/docs. The API has no authentication and its agent endpoints spend OpenAI tokens, so do not expose it beyond your machine (`fastapi run` listens on all interfaces).

```bash
curl -s http://127.0.0.1:8000/pokemon/Mr.%20Mime
curl -s -X POST http://127.0.0.1:8000/teams/analysis -H 'Content-Type: application/json' -d '{"members": ["charizard", "blastoise", "venusaur"]}'
curl -s -X POST http://127.0.0.1:8000/research -H 'Content-Type: application/json' -d '{"question": "Is Gengar weak to Psychic?"}'
curl -s -X POST http://127.0.0.1:8000/advise -H 'Content-Type: application/json' -d '{"request": "What is Garchomp weak to? Then build me a team of 4 with Garchomp that covers those weaknesses."}'
curl -s -X POST http://127.0.0.1:8000/jobs/battles -H 'Content-Type: application/json' -d '{"side1": [{"pokemon": "garchomp"}, {"pokemon": "pikachu"}], "side2": [{"pokemon": "tyranitar"}, {"pokemon": "gyarados"}], "player1": "agent"}'
curl -s http://127.0.0.1:8000/jobs/JOB_ID
```

| Endpoint | Uses an LLM | Purpose |
|---|---|---|
| `GET /pokemon`, `/pokemon/{name}`, `/pokemon/{name}/learnset`, `/moves/{name}` | No | PokéAPI index page, Pokémon, learnsets, moves |
| `POST /teams/analysis` | No | A team's type weaknesses and coverage |
| `POST /battlers`, `/damage` | No | Validate or compute a default moveset; damage ranges at level 50 |
| `POST /battles` | No | One seeded battle between greedy or random players, with its event log |
| `POST /research` | Yes | Research Agent with grounding check |
| `POST /teams/build` | Yes | Team Composition Agent, re-checked by code |
| `POST /teams/optimize` | Yes | Team Optimization Agent (claim checks, score-gated swaps) |
| `POST /advise` | Yes | Supervisor over all agents (`optimize`: auto, always, never) |
| `POST /scout` | Yes | Opponent Analysis Agent (threats, verified counters) |
| `POST /jobs/battles` | Optional | Background battles, including the Battle Strategy Agent; many seeds |
| `POST /jobs/battle-evals`, `/jobs/battle-feedback` | Optional | Battle win rates with 95% CIs and mistakes; train/test feedback loop |
| `POST /jobs/research-evals`, `/jobs/compare` | Yes | Research and team-building evaluation suites |
| `GET /jobs/{id}` | — | Job status, progress, result or error |

Agent responses are `{"result": ..., "usage": ...}` with the model's token usage and tool calls. Jobs answer `202` with a job id; poll `GET /jobs/{id}` until `status` is `succeeded` or `failed`. Errors are `{"detail": ...}`: 404 not found, 422 invalid input, 502 the model or its credentials failed, 503 PokéAPI or the model unavailable.

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pytest -m network
uv run pytest -m openai
```

Default tests are offline. `network` tests call PokéAPI; `openai` tests call the live model and cost money.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — what is implemented
- [docs/PROGRESS.md](docs/PROGRESS.md) — phases, steps and results
- [CLAUDE.md](CLAUDE.md) — project vision, roadmap and development rules

## Disclaimer

PokéVerse AI is an unofficial fan project for learning purposes. It is not affiliated with or endorsed by Nintendo, The Pokémon Company or Game Freak. Pokémon data comes from PokéAPI.