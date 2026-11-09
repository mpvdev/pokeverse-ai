# Architecture

> Describes what is **actually implemented**. Planned architecture lives in [CLAUDE.md](../CLAUDE.md).

## Overview

```text
PokéAPI (upstream, source of truth for every read)
   │
   v
PokéAPI client ──> PokemonCatalog (fetch every lookup, reuse within one request)
                        │  writes a mirror to SQLite (Pokémon, types, base stats, learnsets, moves)
                        v
deterministic core: type chart, team analysis, battlers, battle stats, damage, battle engine,
                    default movesets, baseline players, matchups, mistake review
                        │  read-only tools
                        v
agents (LLM): Research, Team Composition, Team Optimization, Supervisor, Battle Strategy,
              Opponent Analysis, Battle Evaluation
                        │  output re-checked by code
                        v
REST API (FastAPI): lookups and deterministic endpoints, agent endpoints, background jobs (battles, evaluations)
```

Principles:

- Deterministic code owns facts and rules (types, matchups, team scoring). LLMs read them through tools and never write reference data.
- Model output is constrained by strict schemas, re-validated in Python, and re-checked by code before it is shown.
- Facts pass between agents only from tool outputs, never from model prose.
- The catalog always reads from PokéAPI and syncs what it reads to SQLite; nothing is served from SQLite, so a PokéAPI outage fails catalog lookups.

## Repository Layout

```text
pokeverse-ai/
├── src/pokeverse/
│   ├── model.py           # FrozenModel, NonBlank: shared frozen, strict pydantic base
│   ├── paths.py           # default_db_path (POKEVERSE_DB / XDG data dir)
│   ├── api/
│   │   ├── main.py        # the served app: loads .env, then create_app() (FastAPI CLI entrypoint)
│   │   ├── app.py         # create_app, catalog/LLM/runner providers, NameOrId/Name, error → HTTP, /health
│   │   ├── agents.py      # /research, /teams/build, /teams/optimize, /advise, /scout
│   │   ├── battles.py     # /battlers, /damage, /battles (code players)
│   │   ├── catalog.py     # /pokemon, /pokemon/{id}, /pokemon/{id}/learnset, /moves/{id}
│   │   ├── jobs.py        # JobStore, /jobs/{id}, /jobs/battles, battle-evals, battle-feedback, research-evals, compare
│   │   └── teams.py       # /teams/analysis
│   ├── agents/
│   │   ├── answers.py     # PokedexAnswer (its schema is generated from the model)
│   │   ├── battle_review.py    # BattleReviewAgent: lessons citing engine-detected mistakes
│   │   ├── battle_strategy.py  # BattleStrategyAgent: LLM battle Player over code-computed facts
│   │   ├── context.py     # SharedContext: verified facts handed between agents
│   │   ├── generalist.py  # GeneralistAgent: single-agent baseline
│   │   ├── opponent_analysis.py  # OpponentAnalysisAgent: threats + code-verified counters
│   │   ├── optimizer.py   # TeamOptimizationAgent: claim checks + score-gated swaps
│   │   ├── research.py    # ResearchAgent + ResearchResult (grounding check)
│   │   ├── supervisor.py  # Supervisor: specialists as tools, Delegation trace
│   │   ├── team_builder.py  # TeamCompositionAgent, TeamProposal, TeamBuildResult
│   │   └── tools.py       # get_pokemon, get_type_matchups, analyze_team, score_team tools
│   ├── evals/
│   │   ├── battles.py     # battle scenarios, win rate + 95% CI, mistakes, feedback experiment
│   │   ├── compare.py     # single vs multi-agent comparison on fixed tasks
│   │   └── research.py    # Research Agent eval cases + deterministic checks
│   ├── teams/
│   │   ├── models.py      # Team (1-6 Pokémon, repeats allowed)
│   │   └── analysis.py    # analyze_team: exposures, vulnerabilities, gaps
│   ├── battles/
│   │   ├── battler.py     # Battler (Pokémon + 1-4 validated moves), load_battler
│   │   ├── stats.py       # level-50 BattleStats from base stats
│   │   ├── damage.py      # Gen 6+ damage formula, ranges, seeded rolls, expected damage
│   │   ├── engine.py      # BattleState, legal actions, turns, run_battle, events
│   │   ├── matchups.py    # deterministic one-on-one matchups
│   │   ├── movesets.py    # move_score, choose_moveset, default_battler
│   │   ├── players.py     # RandomPlayer, GreedyPlayer
│   │   └── review.py      # RecordingPlayer, deterministic mistake detection
│   ├── catalog/
│   │   ├── __init__.py    # Public catalog API (re-exports models, catalog, errors)
│   │   ├── models.py      # Pokemon, BaseStats, Move, DamageClass, PokemonType, parse_identifier
│   │   ├── pokeapi.py     # PokéAPI HTTP client + payload mapping
│   │   ├── repository.py  # SQLite persistence (schema v4)
│   │   ├── service.py     # PokemonCatalog (PokéAPI every lookup, SQLite mirror), StaticSource
│   │   └── type_chart.py  # Gen 6+ type chart, effectiveness, defensive profiles
│   └── llm/
│       ├── config.py      # LlmSettings (model id, temperature, max tokens, reasoning effort)
│       ├── tools.py       # Provider-neutral Tool / ToolCall
│       ├── structured.py  # Provider-neutral OutputSchema, generated from pydantic models
│       └── openai.py      # OpenAIChat (Responses API, tool loop) + LLM error types
└── tests/                 # mirrors src/pokeverse; offline by default
    ├── test_paths.py
    ├── agents/            # fake ChatModel / scripted completions
    ├── api/               # TestClient over a temp DB, a mocked PokéAPI, a scripted LLM, synchronous jobs
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
| REST API | `pokeverse.api` | The only interface (the Typer CLI was removed). FastAPI app factory `create_app(catalogs, chats, runner)`; `pokeverse.api.main:app` is the served instance (it loads `.env` first, so tests that call `create_app` stay hermetic). The catalog is injected as a provider stored on `app.state` (a context manager yielding a `PokemonCatalog`), opened per request in the handler's thread because SQLite connections are per thread; tests swap in their own. `GET /health`; `GET /pokemon?limit=&offset=` (one page of the PokéAPI index, names and ids, 1–100 per page), `/pokemon/{name_or_id}`, `/pokemon/{name_or_id}/learnset`, `/moves/{name_or_id}`; `POST /teams/analysis` (`{"members": [...]}` → `TeamAnalysis`), `POST /battlers` (`{"pokemon", "moves"}` → `Battler`; no moves = default moveset), `POST /damage` (attacker, move, defender → level-50 range, critical maximum, effectiveness, STAB), `POST /battles` (`side1`/`side2` of battler specs, `player1`/`player2` greedy|random, `seed` → resolved teams, winner, turns and every `BattleEvent`; the same request gives the same battle). Request bodies are strict `FrozenModel`s with `list` fields (FastAPI hands JSON arrays over as lists, which strict mode will not coerce to tuples); unknown fields are rejected. Names in paths and bodies are normalized like agent input (`NameOrId`, `MoveName`); invalid ones, sizes and player names → 422 before any lookup. Domain rule violations (unlearnable or unsupported move, status move in `/damage`) → 422 with the rule's message. Not found → 404, upstream unavailable → 503 (`{"detail": …}`). Responses are the pydantic models, so the OpenAPI schema (`/docs`, `/openapi.json`) comes from them. |
| Agent endpoints | `pokeverse.api.agents` | One synchronous request per agent run (seconds to about a minute): `POST /research` (`question`), `/teams/build` (`request`), `/teams/optimize` (`members`, `goal`, `keep`, `notes`), `/advise` (`request`, `optimize` auto/always/never), `/scout` (`side1`, `side2` battler specs). Each returns `{"result", "usage"}`: the agent's pydantic result (computed fields such as `ungrounded`, `self_checked`, claim `correct`, the supervisor's `facts` and token split) and `Usage` from the observed completion (model, tokens, latency, tool calls with their arguments). The LLM client comes from an injected provider (`app.state.chats`, default `OpenAIChat`), created per request, so missing credentials fail before any work; tests inject a scripted fake that runs the agents' real tools. Prompts are capped at 2,000 characters. Errors: `LlmUnavailableError` → 503; `LlmAuthError` and `LlmRequestError` (a reply that fails validation, an invented Pokémon) → 502, since the model or the server's credentials failed, not the caller. |
| Background jobs | `pokeverse.api.jobs` | Long work runs off the request: `POST /jobs/battles` (any players including `agent`, with an optional scouting run, `runs` up to 1,000 seeds, event logs optional), `/jobs/battle-evals`, `/jobs/battle-feedback`, `/jobs/research-evals`, `/jobs/compare` validate the request (scenario, system and case ids are `Literal` enums; LLM credentials are checked at submission), answer 202 with the `Job` and a `Location` header, and `GET /jobs/{id}` returns `status` (queued → running → succeeded / failed), timestamps, `progress` lines, the `result` (a JSON object built from the evals' `to_dict()`), or an `error` with a kind (`not_found`, `invalid_input`, `upstream_unavailable`, `llm_unavailable`, `llm_auth`, `llm_request`, `internal`). `JobStore` is in-memory and thread-safe, replacing a frozen `Job` snapshot on every change; work runs on a 2-thread pool owned by the app (shut down with it) or an injected runner (tests run jobs synchronously). Failed evaluation cases are results, not job failures; `compare` keeps finished runs when an outage aborts it. Jobs are lost on restart and never pruned. |
| Catalog models | `pokeverse.catalog.models` | Immutable, self-validating reference data as frozen, strict pydantic models (`FrozenModel`: no type coercion, no unknown fields): `Pokemon` (slug name, 1–2 types, required `BaseStats`, `learnset` of move slugs), `BaseStats` (six base stats, each 1–255, `total`) and the `PokemonType` enum. `Pokemon.to_dict()` includes `base_stats`; `to_dict(stats=False)` omits them (used for team members, where analysis is type-based); the learnset is never serialized. `Move`: slug name, type, `DamageClass` (physical/special/status), `power` (`None` for status and fixed-damage moves; status moves never have power), `accuracy` (`None` = never misses), `priority` (−7…+5), `pp` (1–40). |
| PokéAPI client | `pokeverse.catalog.pokeapi` | Fetches a Pokémon (`/pokemon`: types, all six base stats and the learnset's move names) or a move (`/move`) by name/id, or one page of the Pokémon index (`/pokemon?limit=&offset=`, ids parsed from the entry URLs); maps payloads to validated models (moves outside the model, such as Shadow moves and Z-moves, are rejected), and translates HTTP/network failures into typed `PokeApiError` subclasses. A runtime dependency: every catalog lookup goes through it. |
| Repository | `pokeverse.catalog.repository` | `SqlitePokemonRepository`: tables `pokemon`, `pokemon_type` (slot-ordered), `pokemon_stats`, `pokemon_learnset` (JSON array of move slugs) and `move`, schema version 4 in `PRAGMA user_version`, atomic upserts. Older versions are upgraded in place (all DDL is `CREATE ... IF NOT EXISTS`). A write-only mirror of what the catalog fetched: the catalog never reads it (its read methods remain for tests and future use). |
| Catalog service | `pokeverse.catalog.service` | `PokemonCatalog(repository, source)`: `get` (Pokémon), `get_move` and `index(limit, offset)` always fetch from the `PokemonSource` (e.g. `PokeApiClient`) and sync Pokémon and moves to the repository; within one instance (one API request or job) each record is fetched once and reused. Raises `PokemonNotInCatalogError` / `MoveNotInCatalogError` (does not exist upstream) or `UpstreamUnavailableError` (outage, rate limit, bad payload — including for previously synced records). `StaticSource` is a fixed in-memory source for tests. |
| LLM client | `pokeverse.llm` | `OpenAIChat.complete()` sends a Responses API request and returns a `Completion` (text, status, summed token usage, latency, `tool_calls`). With `tools`, it runs a bounded loop (default 5 rounds): execute each `function_call`, send back the model output plus `function_call_output`, repeat until a text reply. Tools are provider-neutral `Tool` objects sent in strict mode. With an `OutputSchema`, the final reply is constrained by a strict `text.format` JSON Schema and parsed into `Completion.data`. `OutputSchema.from_model` generates that schema from a pydantic model (refs inlined, titles, defaults and class docstrings dropped, field descriptions kept; models strict mode would reject are refused), and `parse_reply(model, completion)` validates the reply against the same model as strict JSON, raising `LlmRequestError` with the failing field and the partial usage. Every agent reply is defined once, as a model; per-call enums (battle options, team slots, mistake ids) are `Literal` types in models built with `create_model`. Truncated replies (`status=incomplete`) and refusals raise instead of being parsed. Errors mapped to `LlmAuthError`, `LlmUnavailableError`, `LlmRequestError`; an `LlmRequestError` raised after work began carries the partial `Completion` (usage and tool calls so far). |
| Structured answers | `pokeverse.agents.answers` | `PokedexAnswer` (`answer`, `pokemon` slugs, `confidence` enum), a frozen pydantic model, and `POKEDEX_ANSWER_SCHEMA` generated from it. The schema constrains generation; `parse_reply` re-validates in Python, so model output is never trusted unchecked. Agent results are pydantic models as well: derived values are computed fields, and the `Completion` they carry is excluded from their JSON. |
| Research Agent | `pokeverse.agents.research` | `ResearchAgent.ask()` combines a fixed system prompt, the catalog tool and the `PokedexAnswer` schema. Returns `ResearchResult` with `looked_up` (names from successful tool calls) and `ungrounded` (claimed Pokémon never confirmed by a lookup) — a deterministic hallucination signal. Depends on a `ChatModel` protocol, not on OpenAI. |
| Evaluation | `pokeverse.evals` | `RESEARCH_CASES` (fixed questions with expected Pokémon, required facts, whether a lookup is expected, tools that must be called, words that must not appear) and `check()`; `run_case()` records model misbehaviour as a case failure while auth/outage errors abort the run. Live runs only (no recorded model responses). |
| Multi-agent comparison | `pokeverse.evals.compare` | `COMPARE_CASES` run on four systems: `single` (`GeneralistAgent`, one agent with every tool), `multi` (`Supervisor(optimize="never")`), `multi+auto` (`"auto"`) and `multi+opt` (`"always"`). Scored only by code: regex facts, team size, required members, allowed types, attack types the team must resist, max vulnerabilities, and that the answer names the produced team. The team is taken from observed output (optimizer's final, else the builder's) and re-analyzed; specialist errors are listed only when a run fails. |
| Catalog tools | `pokeverse.agents.tools` | `make_catalog_tools(catalog)` returns two read-only tools: `get_pokemon` (returns `Pokemon.to_dict()`, including base stats) and `get_type_matchups` (the Pokémon plus `weak_to` / `resists` / `immune_to` multipliers from the type chart). Both normalize model input (`"Mr. Mime"` → `mr-mime`, `"#025"` → 25) and report catalog failures as `{"error", "message"}` data so the model can explain them. |
| Type chart | `pokeverse.catalog.type_chart` | Deterministic Gen 6+ type effectiveness: `TYPE_CHART` (non-1× entries only), `effectiveness(attacking, defending_types)`, `defensive_profile(types)`. Hard-coded reference data, checked against PokéAPI by an opt-in network test. |
| Teams | `pokeverse.teams` | Application state, separate from reference data, as frozen, strict pydantic models. `Team`: immutable 1–6 Pokémon; the same species may repeat, and each copy counts as a separate member in the analysis. `analyze_team(team)` → `TeamAnalysis`: per-attacking-type exposure (weak / resists / immune members), `vulnerabilities` (≥2 weak and weak outnumber cover), `unresisted` types, STAB-only `offensive_gaps`, and a comparable `score` tuple (lower is better); the derived values are computed fields, so they appear in the model's JSON. `to_dict()` stays the compact shape agents read (members without stats). Pure code over the type chart; agents read it rather than judge teams themselves. |
| Battlers | `pokeverse.battles` | `Battler` (pydantic): an immutable Pokémon plus 1–4 distinct moves, each in its learnset and supported by the engine (`is_battle_move`: power-based damage, not in `UNMODELLED_MOVES` — self-KO, recharge, charge-turn, conditional, HP-scaled, self-damaging and non-standard-stat moves). `load_battler(catalog, pokemon, moves)` checks the move count and learnset before fetching move details. |
| Battle stats and damage | `pokeverse.battles.stats`, `pokeverse.battles.damage` | Pure functions. `battle_stats` derives level-50 stats (31 IVs, 0 EVs, neutral nature) and is cached per `BaseStats` (it is called on every damage calculation). `calculate_damage` implements the Gen 6+ formula in Pokémon Showdown's integer order (base damage, critical ×1.5, roll 85–100%, STAB ×1.5 rounded half down, type effectiveness, minimum 1 unless immune); `damage_range` gives min/max without a critical hit; `roll_damage` draws the critical hit (1 in 24) and roll from an injected `random.Random`, so battles can be replayed from a seed. |
| Battle engine | `pokeverse.battles.engine` | Singles battles between two teams of 1–6 battlers as pure transitions over immutable `BattleState` (two `Side`s of `Combatant`s with current HP; all engine types are frozen, strict pydantic models, and transitions use `model_copy`, which skips re-validation). `legal_actions` lists `UseMove`/`Switch` choices and every choice is validated against it (`IllegalActionError`). `play_turn`: switches first, then moves by priority, speed and a seeded tie-break; immunity before the accuracy roll; knocked-out battlers do not act. `replace_fainted` handles forced switches. `run_battle` drives two `Player`s (protocol: `choose(state, side, options)`) to a win or a draw at `MAX_TURNS` and returns structured `BattleEvent`s. PP is not tracked. |
| Default movesets | `pokeverse.battles.movesets` | `move_score` (power × accuracy × STAB × matching attack stat); `choose_moveset`: best-scoring move first, then the best moves adding super-effective coverage, one per type; `default_battler` resolves every learnable move through the catalog (about 100 PokéAPI requests per Pokémon per request or job) and fails rather than choose from a partial learnset. |
| Baseline players | `pokeverse.battles.players` | Code-only `Player`s to compare agents against: `RandomPlayer` (uniform over legal actions, own seeded RNG) and `GreedyPlayer` (highest expected damage this turn, capped at the foe's HP, priority as tie-break; switches only when no move can hurt; replaces with the best attacker). `make_player(name, rng)`. |
| Battle Strategy Agent | `pokeverse.agents.battle_strategy` | `BattleStrategyAgent` implements the battle `Player` protocol with one LLM call per decision and no tools. `describe_situation` writes code-computed facts into the prompt (HP, speed order, the foe's threats, every legal option with exact damage ranges, % of remaining HP and KO flags, and each switch's incoming threat and answer). The strict output schema is built per decision with the legal option ids as an enum, and the engine validates the choice again. One legal option → no model call. Malformed or refused replies fall back to `GreedyPlayer` and are flagged; auth/outage errors abort. Records `BattleDecision`s (turn, option, reason, fallback, tokens). With an `OpponentAnalysis`, each prompt ends with its briefing rendered for the current state. |
| Matchups | `pokeverse.battles.matchups` | `matchup(attacker, defender)` → `Matchup`: each side's best move (expected damage), damage ranges, who moves first (priority, then speed), hits to KO with minimum rolls (misses and critical hits ignored), and `wins` for the full-HP one-on-one. Pure code; the basis for opponent analysis and its checks. |
| Opponent Analysis Agent | `pokeverse.agents.opponent_analysis` | `OpponentAnalysisAgent.analyze(own, foe)`: one LLM call over the code-computed matchup table; strict output with team slots as enums (`own-1:pikachu`, `foe-0:tyranitar`): threats (every foe ranked once by danger), counters and a plan. Code rejects incomplete rankings and marks each counter `verified` only if the matchup says our member wins. `OpponentAnalysis.briefing(state, side)` hands the strategy agent only the threat ranking and verified counters, minus knocked-out Pokémon; the plan prose is shown to the user, not handed over. |
| Mistake review | `pokeverse.battles.review` | `RecordingPlayer` wraps any player and records each choice with its state. `judge` flags only clear-cut mistakes from engine facts: `missed_ko` (a guaranteed, can't-miss knockout that lands before the foe moves was available), `no_effect` (an immune target while a damaging move existed), `switched_into_ko` (the incoming Pokémon is a guaranteed KO for the foe). Forced replacements are not judged. Applies to code and LLM players alike. |
| Battle Evaluation Agent | `pokeverse.agents.battle_review` | `BattleReviewAgent.review(mistakes)`: one LLM call turning engine-detected mistakes into at most 3 general lessons, each citing mistake ids (enum); uncited lessons are dropped by code; no mistakes → no call. `BattleReview.guidance()` is appended to the Battle Strategy Agent's prompts (`lessons=`). |
| Battle evaluation | `pokeverse.evals.battles` | Fixed `BATTLE_SCENARIOS` (side 1 vs a greedy side 2, default movesets). `run_system` plays a system (`greedy`, `agent`, `agent+analysis`, `agent+lessons`) over seeds and reports wins, draws, win rate with a Wilson 95% interval, average turns, mistakes per battle, tokens per battle (analysis included) and fallbacks. `feedback_experiment` learns lessons on training seeds and compares the agent with and without them on disjoint test seeds; with no lessons it stops before spending test tokens. |
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
- Dependencies managed with uv (`uv.lock`). Runtime: FastAPI and FastAPI CLI (which brings uvicorn), httpx, pydantic, OpenAI SDK, python-dotenv.
- REST API: `uv run fastapi dev` (auto-reload, listens on 127.0.0.1 only) or `uv run fastapi run` (all interfaces); the app is `pokeverse.api.main:app`, set in `[tool.fastapi] entrypoint` in `pyproject.toml`. Serves http://127.0.0.1:8000, interactive docs at `/docs`. No authentication yet: agent endpoints and jobs spend OpenAI tokens, so the server must not be exposed beyond the local machine.
- Background jobs run on a 2-thread pool inside the server process; jobs live in memory.
- Persistence: a SQLite mirror of everything fetched from PokéAPI, by default `~/.local/share/pokeverse/catalog.db` (outside the repo); written, never read. PokéAPI must be reachable for any catalog lookup.
- LLM inference temporarily uses the OpenAI Responses API (default model `gpt-6-luna`, override with `POKEVERSE_MODEL_ID`; `POKEVERSE_REASONING_EFFORT` defaults to `none`, and temperature is only sent when it is `none`); credentials come from `OPENAI_API_KEY`, either exported or read from a git-ignored `.env` in the working directory when the server starts (exported values win). Network access: PokéAPI client and OpenAI.
