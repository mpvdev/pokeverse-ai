# Architecture

> Describes what is **actually implemented**. Planned architecture lives in [CLAUDE.md](../CLAUDE.md).

## Overview

```text
PokéAPI (upstream, import only)
   │
   v
PokéAPI client ──> local catalog (SQLite: Pokémon, types, base stats, learnsets, moves)
                        │  PokemonCatalog (local-first)
                        v
deterministic core: type chart, team analysis, battlers
                        │  read-only tools
                        v
agents (LLM): Research, Team Composition, Team Optimization, Supervisor
                        │  output re-checked by code
                        v
CLI (pokeverse …) and evaluations
```

Principles:

- Deterministic code owns facts and rules (types, matchups, team scoring). LLMs read them through tools and never write reference data.
- Model output is constrained by strict schemas, re-validated in Python, and re-checked by code before it is shown.
- Facts pass between agents only from tool outputs, never from model prose.
- The catalog is local-first: stored data never depends on PokéAPI being available.

## Repository Layout

```text
pokeverse-ai/
├── src/pokeverse/
│   ├── __main__.py        # `python -m pokeverse` entry point
│   ├── cli.py             # Typer app; `pokeverse` console script
│   ├── agents/
│   │   ├── answers.py     # PokedexAnswer + its strict JSON Schema
│   │   ├── context.py     # SharedContext: verified facts handed between agents
│   │   ├── generalist.py  # GeneralistAgent: single-agent baseline
│   │   ├── optimizer.py   # TeamOptimizationAgent: claim checks + score-gated swaps
│   │   ├── research.py    # ResearchAgent + ResearchResult (grounding check)
│   │   ├── supervisor.py  # Supervisor: specialists as tools, Delegation trace
│   │   ├── team_builder.py  # TeamCompositionAgent, TeamProposal, TeamBuildResult
│   │   └── tools.py       # get_pokemon, get_type_matchups, analyze_team, score_team tools
│   ├── evals/
│   │   ├── compare.py     # single vs multi-agent comparison on fixed tasks
│   │   └── research.py    # Research Agent eval cases + deterministic checks
│   ├── teams/
│   │   ├── models.py      # Team (1-6 Pokémon, repeats allowed)
│   │   └── analysis.py    # analyze_team: exposures, vulnerabilities, gaps
│   ├── battles/
│   │   └── battler.py     # Battler (Pokémon + 1-4 validated moves), load_battler
│   ├── catalog/
│   │   ├── __init__.py    # Public catalog API (re-exports models, catalog, errors)
│   │   ├── models.py      # Pokemon, BaseStats, Move, DamageClass, PokemonType, parse_identifier
│   │   ├── pokeapi.py     # PokéAPI HTTP client + payload mapping
│   │   ├── repository.py  # SQLite persistence (schema v4)
│   │   ├── service.py     # Local-first PokemonCatalog
│   │   └── type_chart.py  # Gen 6+ type chart, effectiveness, defensive profiles
│   └── llm/
│       ├── config.py      # LlmSettings (model id, temperature, max tokens, reasoning effort)
│       ├── tools.py       # Provider-neutral Tool / ToolCall
│       ├── structured.py  # Provider-neutral OutputSchema
│       └── openai.py      # OpenAIChat (Responses API, tool loop) + LLM error types
└── tests/                 # mirrors src/pokeverse; offline by default
    ├── test_cli.py
    ├── test_package.py
    ├── agents/            # fake ChatModel / scripted completions
    ├── battles/
    ├── catalog/
    │   └── fixtures/pokeapi/  # trimmed real PokéAPI responses
    ├── evals/
    ├── llm/               # injected fake OpenAI client, no network
    └── teams/
```

## Components

| Component | Module | Responsibility |
|-----------|--------|----------------|
| CLI | `pokeverse.cli` | Typer app. `pokemon <name|id> [--json] [--offline]`, `move <name|id> [--json] [--offline]`, `learnset <pokemon> [--json] [--offline]`, `moveset <pokemon> <move>... [--json] [--offline]` (validates a battler) and `list [--json]` over the local catalog (names normalized like agent input: `"Mr. Mime"`, `"Swords Dance"`, `#006`); `ask <question> [--no-tools] [--json]` asks the LLM, which can look Pokémon up via the catalog tool (`--usage` traces tool calls; `--json` prints a validated `PokedexAnswer`). `research <question> [--json] [--usage]` runs the Research Agent and warns on ungrounded claims; `eval [--case ID]` runs the evaluation suite; `team <names…> [--json] [--offline]` analyzes a team; `build "<request>" [--json] [--usage]` runs the Team Composition Agent and prints our own analysis of its team; `advise "<request>" [--optimize auto|always|never] [--json] [--usage]` runs the Supervisor and can show delegations and the supervisor/specialist token split; `optimize <names…> [--goal] [--keep] [--notes] [--json] [--usage]` runs the Team Optimization Agent; `compare [--case] [--system] [--json]` runs the single- vs multi-agent comparison. DB path from `--db`, `POKEVERSE_DB`, or `$XDG_DATA_HOME/pokeverse/catalog.db`. Exit codes: 0 ok, 1 not found, 2 invalid input, 3 upstream unavailable, 4 auth/credentials, 5 eval failures; errors on stderr. |
| Catalog models | `pokeverse.catalog.models` | Immutable, self-validating reference data: `Pokemon` (slug name, 1–2 types, required `BaseStats`, `learnset` of move slugs), `BaseStats` (six base stats, each 1–255, `total`) and the `PokemonType` enum. `Pokemon.to_dict()` includes `base_stats`; `to_dict(stats=False)` omits them (used for team members, where analysis is type-based); the learnset is never serialized. `Move`: slug name, type, `DamageClass` (physical/special/status), `power` (`None` for status and fixed-damage moves; status moves never have power), `accuracy` (`None` = never misses), `priority` (−7…+5), `pp` (1–40). |
| PokéAPI client | `pokeverse.catalog.pokeapi` | Fetches a Pokémon (`/pokemon`: types, all six base stats and the learnset's move names) or a move (`/move`) by name/id, maps payloads to validated models (moves outside the model, such as Shadow moves and Z-moves, are rejected), and translates HTTP/network failures into typed `PokeApiError` subclasses. Import-only; not a runtime dependency. |
| Repository | `pokeverse.catalog.repository` | `SqlitePokemonRepository`: tables `pokemon`, `pokemon_type` (slot-ordered), `pokemon_stats`, `pokemon_learnset` (JSON array of move slugs) and `move`, schema version 4 in `PRAGMA user_version`, atomic upserts. Older versions are upgraded in place (all DDL is `CREATE ... IF NOT EXISTS`). A Pokémon is only read when its stats and learnset rows exist (inner joins), so rows imported under older schemas count as misses and are re-imported on the next online lookup; moves are kept. |
| Catalog service | `pokeverse.catalog.service` | `PokemonCatalog`: `get` (Pokémon) and `get_move` read locally first; on a miss they import via a `PokemonSource` (e.g. `PokeApiClient`) and store the result. Raises `PokemonNotInCatalogError` / `MoveNotInCatalogError` or `UpstreamUnavailableError`; cached data never depends on upstream. |
| LLM client | `pokeverse.llm` | `OpenAIChat.complete()` sends a Responses API request and returns a `Completion` (text, status, summed token usage, latency, `tool_calls`). With `tools`, it runs a bounded loop (default 5 rounds): execute each `function_call`, send back the model output plus `function_call_output`, repeat until a text reply. Tools are provider-neutral `Tool` objects sent in strict mode. With an `OutputSchema`, the final reply is constrained by a strict `text.format` JSON Schema and parsed into `Completion.data`. Truncated replies (`status=incomplete`) and refusals raise instead of being parsed. Errors mapped to `LlmAuthError`, `LlmUnavailableError`, `LlmRequestError`; an `LlmRequestError` raised after work began carries the partial `Completion` (usage and tool calls so far). |
| Structured answers | `pokeverse.agents.answers` | `PokedexAnswer` (`answer`, `pokemon` slugs, `confidence` enum) and `POKEDEX_ANSWER_SCHEMA`. The schema constrains generation; `PokedexAnswer.from_dict` re-validates in Python, so model output is never trusted unchecked. |
| Research Agent | `pokeverse.agents.research` | `ResearchAgent.ask()` combines a fixed system prompt, the catalog tool and the `PokedexAnswer` schema. Returns `ResearchResult` with `looked_up` (names from successful tool calls) and `ungrounded` (claimed Pokémon never confirmed by a lookup) — a deterministic hallucination signal. Depends on a `ChatModel` protocol, not on OpenAI. |
| Evaluation | `pokeverse.evals` | `RESEARCH_CASES` (fixed questions with expected Pokémon, required facts, whether a lookup is expected, tools that must be called, words that must not appear) and `check()`; `run_case()` records model misbehaviour as a case failure while auth/outage errors abort the run. Live runs only (no recorded model responses). |
| Multi-agent comparison | `pokeverse.evals.compare` | `COMPARE_CASES` run on four systems: `single` (`GeneralistAgent`, one agent with every tool), `multi` (`Supervisor(optimize="never")`), `multi+auto` (`"auto"`) and `multi+opt` (`"always"`). Scored only by code: regex facts, team size, required members, allowed types, attack types the team must resist, max vulnerabilities, and that the answer names the produced team. The team is taken from observed output (optimizer's final, else the builder's) and re-analyzed; specialist errors are listed only when a run fails. |
| Catalog tools | `pokeverse.agents.tools` | `make_catalog_tools(catalog)` returns two read-only tools: `get_pokemon` (returns `Pokemon.to_dict()`, including base stats) and `get_type_matchups` (the Pokémon plus `weak_to` / `resists` / `immune_to` multipliers from the type chart). Both normalize model input (`"Mr. Mime"` → `mr-mime`, `"#025"` → 25) and report catalog failures as `{"error", "message"}` data so the model can explain them. |
| Type chart | `pokeverse.catalog.type_chart` | Deterministic Gen 6+ type effectiveness: `TYPE_CHART` (non-1× entries only), `effectiveness(attacking, defending_types)`, `defensive_profile(types)`. Hard-coded reference data, checked against PokéAPI by an opt-in network test. |
| Teams | `pokeverse.teams` | Application state, separate from reference data. `Team`: immutable 1–6 Pokémon; the same species may repeat, and each copy counts as a separate member in the analysis. `analyze_team(team)` → `TeamAnalysis`: per-attacking-type exposure (weak / resists / immune members), `vulnerabilities` (≥2 weak and weak outnumber cover), `unresisted` types, STAB-only `offensive_gaps`, and a comparable `score` tuple (lower is better). Pure code over the type chart; agents will read it rather than judge teams themselves. |
| Battlers | `pokeverse.battles` | `Battler`: an immutable Pokémon plus 1–4 distinct moves, each in its learnset and with a fixed power (status and fixed-damage moves are rejected until the engine supports them). `load_battler(catalog, pokemon, moves)` checks the move count and learnset before fetching move details. |
| Team Composition Agent | `pokeverse.agents.team_builder` | `TeamCompositionAgent.build(request)`: free-text request → `TeamProposal` (members with roles, summary) using `get_pokemon`, `get_type_matchups` and `analyze_team` (from `make_team_tools`), with a larger tool-round and token budget than research. The result (`TeamBuildResult`) is re-checked by code: members resolved through the catalog (invented Pokémon rejected), analysis recomputed, and `self_checked` reports whether the agent analyzed exactly the final team. |
| Supervisor | `pokeverse.agents.supervisor` | `Supervisor.run(request)`: an LLM whose tools are the specialist agents (`ask_research_agent`, `ask_team_builder`, each taking a self-contained `task`). It never answers Pokémon facts itself and composes its answer from specialist results. Each tool call runs the real specialist (with its own prompt, tools and validation) and returns its `to_dict()`; specialist failures come back as error data. `SupervisorResult` holds the answer, the observed `Delegation` trace and the supervisor/specialist token split. `optimize` mode: `never` (no optimizer tool), `auto` (default: after a successful build, code runs the optimizer only if the team has vulnerabilities, with the user's required members as `keep`; the builder's tool result then includes `optimization`), `always` (the supervisor is instructed to optimize every built team). |
| Shared context | `pokeverse.agents.context` | `SharedContext`, one per supervised request: records verified facts from specialists' tool outputs only (never model prose) and renders them as a "Verified facts" block appended to the next specialist's task. Each `Delegation` records its `handoff`; Pokémon handed over count as grounded for the Research Agent. |
| Team Optimization Agent | `pokeverse.agents.optimizer` | `TeamOptimizationAgent.optimize(team, goal, keep, notes, facts)`. The model extracts type claims from the notes and proposes up to 3 swaps, exploring candidates with the compact `score_team` tool. Code decides: each claim is checked against the type chart (`ClaimCheck`), and swaps are applied in order and kept only if `TeamAnalysis.score` strictly improves and no `keep` member is removed (`SwapDecision` with a verdict). Returns `OptimizationResult` (original and final analysis, swaps, claims, critique). Exposed to the Supervisor as `ask_team_optimizer`. |

## Agent Flow

```text
user request ──> Supervisor (LLM) ── ask_research_agent(task) ──> ResearchAgent ──> catalog tools
                      │                      │ tool outputs
                      │                      v
                      │               SharedContext (verified facts)
                      │                      │ "Verified facts" block
                      │                      v
                      │          └─ ask_team_builder(task, keep) ──> TeamCompositionAgent ──> catalog + analyze_team
                      │                │ auto mode: code checks the analysis; vulnerabilities ──> TeamOptimizationAgent
                      │          └─ ask_team_optimizer(members, goal, keep, notes) ──> TeamOptimizationAgent ──> score_team; code checks claims, gates swaps
                      └──> answer composed from specialist results (+ Delegation trace, handoffs, token split)
```

## Runtime

- Python 3.15, packaged with setuptools (`src/` layout).
- Dependencies managed with uv (`uv.lock`). Runtime: Typer, httpx, OpenAI SDK, python-dotenv.
- Persistence: local SQLite file, by default `~/.local/share/pokeverse/catalog.db` (outside the repo).
- LLM inference temporarily uses the OpenAI Responses API (default model `gpt-6-luna`, override with `POKEVERSE_MODEL_ID`; `POKEVERSE_REASONING_EFFORT` defaults to `none`, and temperature is only sent when it is `none`); credentials come from `OPENAI_API_KEY`, either exported or read from a git-ignored `.env` in the working directory (exported values win). Network access: PokéAPI client and OpenAI.
