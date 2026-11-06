# PokéVerse AI

A learning-oriented multi-agent AI platform inspired by Pokémon, built backend-first as a Python CLI.

**Status:** Phase 2 (Multi-Agent Trainer System) complete. Next: Phase 3 — Battle Intelligence. See [docs/PROGRESS.md](docs/PROGRESS.md).

## What it does

- **Pokémon catalog** — looks Pokémon up from [PokéAPI](https://pokeapi.co/) and stores them in a local SQLite catalog, so previously seen Pokémon keep working when PokéAPI is down.
- **Research Agent** — answers Pokémon questions with tool calling and validated, structured answers; a grounding check flags any Pokémon the answer names but never looked up.
- **Type matchups and team analysis** — deterministic code (no LLM): the Gen 6+ type chart, weaknesses, resistances, team vulnerabilities and coverage gaps.
- **Team building** — a Team Composition Agent builds teams from plain-language requests; a Team Optimization Agent fact-checks type claims and proposes swaps, which code keeps only if the team measurably improves.
- **Supervisor** — `advise` routes any request to the right specialist agents and hands verified facts between them.
- **Evaluation** — fixed test suites scored by code, including a single- vs multi-agent comparison with token and latency costs.

Design principle: the LLM handles judgement and language; facts and rules (types, matchups, team scoring) are plain, tested code, and model output is always re-checked before it is shown.

## Requirements

- Python 3.15 and [uv](https://docs.astral.sh/uv/)
- An OpenAI API key for the LLM commands (temporary provider; Amazon Bedrock is the planned AWS target)

## Setup

```bash
uv sync
echo 'OPENAI_API_KEY=sk-...' > .env
```

`.env` is git-ignored. Optional settings: `POKEVERSE_MODEL_ID` (default `gpt-6-luna`), `POKEVERSE_REASONING_EFFORT` (default `none`), `POKEVERSE_DB` (default `~/.local/share/pokeverse/catalog.db`).

## Usage

```bash
uv run pokeverse pokemon "Mr. Mime"
uv run pokeverse team charizard blastoise venusaur
uv run pokeverse research "Is Gengar weak to Psychic?" --usage
uv run pokeverse build "A balanced team of 6 around Pikachu"
uv run pokeverse optimize reshiram turtonator gouging-fire volcanion --goal "Fire-only"
uv run pokeverse advise "What is Garchomp weak to? Then build me a team of 4 with Garchomp that covers those weaknesses." --usage
```

| Command | Uses an LLM | Purpose |
|---|---|---|
| `pokemon`, `list` | No | Look up and list catalog entries |
| `team` | No | Analyze a team's type weaknesses and coverage |
| `ask` | Yes | Raw model playground (optional tools, `--json`) |
| `research` | Yes | Research Agent with grounding check |
| `build` | Yes | Team Composition Agent |
| `optimize` | Yes | Team Optimization Agent (claim checks, score-gated swaps) |
| `advise` | Yes | Supervisor over all agents (`--optimize auto\|always\|never`) |
| `eval`, `compare` | Yes | Evaluation suites (live calls; cost tokens) |

Most commands accept `--json`; LLM commands accept `--usage` to show tool calls and token usage. Exit codes: 0 ok, 1 not found, 2 invalid input, 3 upstream unavailable, 4 authentication, 5 evaluation failures.

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