# Architecture

> Describes what is **actually implemented**. Planned architecture lives in [CLAUDE.md](../CLAUDE.md).

## Current State (Phase 2 complete)

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
│   └── catalog/
│       ├── __init__.py    # Public catalog API (re-exports Pokemon)
│       ├── models.py      # Pokemon, PokemonType, parse_identifier
│       ├── pokeapi.py     # PokéAPI HTTP client + payload mapping
│       ├── repository.py  # SQLite persistence
│       ├── service.py     # Local-first PokemonCatalog
│       └── type_chart.py  # Gen 6+ type chart, effectiveness, defensive profiles
│   └── llm/
│       ├── config.py      # LlmSettings (model id, temperature, max tokens, reasoning effort)
│       ├── tools.py       # Provider-neutral Tool / ToolCall
│       ├── structured.py  # Provider-neutral OutputSchema
│       └── openai.py      # OpenAIChat (Responses API, tool loop) + LLM error types
└── tests/
    ├── test_cli.py
    ├── agents/
    │   ├── test_answers.py
    │   ├── test_research_agent.py
    │   └── test_tools.py
    ├── evals/
    │   └── test_research_evals.py
    └── catalog/
        ├── fixtures/pokeapi/   # recorded PokéAPI responses
        ├── test_models.py
        ├── test_pokeapi.py
        ├── test_repository.py
        └── test_service.py
    └── llm/
        ├── test_config.py
        └── test_openai.py    # injected fake client, no network
```

### Components

| Component | Module | Responsibility |
|-----------|--------|----------------|
| CLI | `pokeverse.cli` | Typer app. `pokemon <name|id> [--json] [--offline]` and `list [--json]` over the local catalog; `ask <question> [--no-tools] [--json]` asks the LLM, which can look Pokémon up via the catalog tool (`--usage` traces tool calls; `--json` prints a validated `PokedexAnswer`). `research <question> [--json] [--usage]` runs the Research Agent and warns on ungrounded claims; `eval [--case ID]` runs the evaluation suite; `team <names…> [--json] [--offline]` analyzes a team; `build "<request>" [--json] [--usage]` runs the Team Composition Agent and prints our own analysis of its team; `advise "<request>" [--optimize auto|always|never] [--json] [--usage]` runs the Supervisor and can show delegations and the supervisor/specialist token split; `optimize <names…> [--goal] [--keep] [--notes] [--json] [--usage]` runs the Team Optimization Agent; `compare [--case] [--system] [--json]` runs the single- vs multi-agent comparison. DB path from `--db`, `POKEVERSE_DB`, or `$XDG_DATA_HOME/pokeverse/catalog.db`. Exit codes: 0 ok, 1 not found, 2 invalid input, 3 upstream unavailable, 4 auth/credentials, 5 eval failures; errors on stderr. |
| Catalog models | `pokeverse.catalog.models` | Immutable, self-validating reference data: `Pokemon` (slug name, 1–2 types) and the `PokemonType` enum. |
| PokéAPI client | `pokeverse.catalog.pokeapi` | Fetches a Pokémon by name/id, maps the payload to `Pokemon`, and translates HTTP/network failures into typed `PokeApiError` subclasses. Import-only; not a runtime dependency. |
| Repository | `pokeverse.catalog.repository` | `SqlitePokemonRepository`: tables `pokemon` and `pokemon_type` (slot-ordered), schema version in `PRAGMA user_version`, atomic upserts. |
| Catalog service | `pokeverse.catalog.service` | `PokemonCatalog`: reads locally first; on a miss imports via a `PokemonSource` (e.g. `PokeApiClient`) and stores the result. Raises `PokemonNotInCatalogError` or `UpstreamUnavailableError`; cached data never depends on upstream. |
| LLM client | `pokeverse.llm` | `OpenAIChat.complete()` sends a Responses API request and returns a `Completion` (text, status, summed token usage, latency, `tool_calls`). With `tools`, it runs a bounded loop (default 5 rounds): execute each `function_call`, send back the model output plus `function_call_output`, repeat until a text reply. Tools are provider-neutral `Tool` objects sent in strict mode. With an `OutputSchema`, the final reply is constrained by a strict `text.format` JSON Schema and parsed into `Completion.data`. Truncated replies (`status=incomplete`) and refusals raise instead of being parsed. Errors mapped to `LlmAuthError`, `LlmUnavailableError`, `LlmRequestError`; an `LlmRequestError` raised after work began carries the partial `Completion` (usage and tool calls so far). |
| Structured answers | `pokeverse.agents.answers` | `PokedexAnswer` (`answer`, `pokemon` slugs, `confidence` enum) and `POKEDEX_ANSWER_SCHEMA`. The schema constrains generation; `PokedexAnswer.from_dict` re-validates in Python, so model output is never trusted unchecked. |
| Research Agent | `pokeverse.agents.research` | `ResearchAgent.ask()` combines a fixed system prompt, the catalog tool and the `PokedexAnswer` schema. Returns `ResearchResult` with `looked_up` (names from successful tool calls) and `ungrounded` (claimed Pokémon never confirmed by a lookup) — a deterministic hallucination signal. Depends on a `ChatModel` protocol, not on OpenAI. |
| Evaluation | `pokeverse.evals` | `RESEARCH_CASES` (fixed questions with expected Pokémon, required facts, whether a lookup is expected, tools that must be called, words that must not appear) and `check()`; `run_case()` records model misbehaviour as a case failure while auth/outage errors abort the run. Live runs only (no recorded model responses). |
| Multi-agent comparison | `pokeverse.evals.compare` | `COMPARE_CASES` run on four systems: `single` (`GeneralistAgent`, one agent with every tool), `multi` (`Supervisor(optimize="never")`), `multi+auto` (`"auto"`) and `multi+opt` (`"always"`). Scored only by code: regex facts, team size, required members, allowed types, attack types the team must resist, max vulnerabilities, and that the answer names the produced team. The team is taken from observed output (optimizer's final, else the builder's) and re-analyzed; specialist errors are listed only when a run fails. |
| Catalog tools | `pokeverse.agents.tools` | `make_catalog_tools(catalog)` returns two read-only tools: `get_pokemon` (returns `Pokemon.to_dict()`) and `get_type_matchups` (the Pokémon plus `weak_to` / `resists` / `immune_to` multipliers from the type chart). Both normalize model input (`"Mr. Mime"` → `mr-mime`, `"#025"` → 25) and report catalog failures as `{"error", "message"}` data so the model can explain them. |
| Type chart | `pokeverse.catalog.type_chart` | Deterministic Gen 6+ type effectiveness: `TYPE_CHART` (non-1× entries only), `effectiveness(attacking, defending_types)`, `defensive_profile(types)`. Hard-coded reference data, checked against PokéAPI by an opt-in network test. |
| Teams | `pokeverse.teams` | Application state, separate from reference data. `Team`: immutable 1–6 Pokémon; the same species may repeat, and each copy counts as a separate member in the analysis. `analyze_team(team)` → `TeamAnalysis`: per-attacking-type exposure (weak / resists / immune members), `vulnerabilities` (≥2 weak and weak outnumber cover), `unresisted` types, STAB-only `offensive_gaps`, and a comparable `score` tuple (lower is better). Pure code over the type chart; agents will read it rather than judge teams themselves. |
| Team Composition Agent | `pokeverse.agents.team_builder` | `TeamCompositionAgent.build(request)`: free-text request → `TeamProposal` (members with roles, summary) using `get_pokemon`, `get_type_matchups` and `analyze_team` (from `make_team_tools`), with a larger tool-round and token budget than research. The result (`TeamBuildResult`) is re-checked by code: members resolved through the catalog (invented Pokémon rejected), analysis recomputed, and `self_checked` reports whether the agent analyzed exactly the final team. |
| Supervisor | `pokeverse.agents.supervisor` | `Supervisor.run(request)`: an LLM whose tools are the specialist agents (`ask_research_agent`, `ask_team_builder`, each taking a self-contained `task`). It never answers Pokémon facts itself and composes its answer from specialist results. Each tool call runs the real specialist (with its own prompt, tools and validation) and returns its `to_dict()`; specialist failures come back as error data. `SupervisorResult` holds the answer, the observed `Delegation` trace and the supervisor/specialist token split. `optimize` mode: `never` (no optimizer tool), `auto` (default: after a successful build, code runs the optimizer only if the team has vulnerabilities, with the user's required members as `keep`; the builder's tool result then includes `optimization`), `always` (the supervisor is instructed to optimize every built team). |
| Shared context | `pokeverse.agents.context` | `SharedContext`, one per supervised request: records verified facts from specialists' tool outputs only (never model prose) and renders them as a "Verified facts" block appended to the next specialist's task. Each `Delegation` records its `handoff`; Pokémon handed over count as grounded for the Research Agent. |
| Team Optimization Agent | `pokeverse.agents.optimizer` | `TeamOptimizationAgent.optimize(team, goal, keep, notes, facts)`. The model extracts type claims from the notes and proposes up to 3 swaps, exploring candidates with the compact `score_team` tool. Code decides: each claim is checked against the type chart (`ClaimCheck`), and swaps are applied in order and kept only if `TeamAnalysis.score` strictly improves and no `keep` member is removed (`SwapDecision` with a verdict). Returns `OptimizationResult` (original and final analysis, swaps, claims, critique). Exposed to the Supervisor as `ask_team_optimizer`. |

### Multi-agent flow (Phase 2)

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

### Runtime

- Python 3.15, packaged with setuptools (`src/` layout).
- Dependencies managed with uv (`uv.lock`). Runtime: Typer, httpx, OpenAI SDK, python-dotenv.
- Persistence: local SQLite file, by default `~/.local/share/pokeverse/catalog.db` (outside the repo).
- LLM inference temporarily uses the OpenAI Responses API (default model `gpt-6-luna`, override with `POKEVERSE_MODEL_ID`; `POKEVERSE_REASONING_EFFORT` defaults to `none`, and temperature is only sent when it is `none`); credentials come from `OPENAI_API_KEY`, either exported or read from a git-ignored `.env` in the working directory (exported values win). Network access: PokéAPI client and OpenAI.

## Phase 1 Shape (implemented)

```text
PokéAPI ──> PokéAPI client ──> normalization ──> local catalog (SQLite)
                                                       │
                                          catalog interface (repository)
                                                       │
                              Research Agent (LLM + tools) ──> CLI
```

Key principle: everything to the left of the agent is deterministic, testable code. The LLM only reads the catalog through tools; it never writes reference data.
