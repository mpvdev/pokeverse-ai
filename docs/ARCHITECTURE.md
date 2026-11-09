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
deterministic core: type chart, team analysis, battlers, battle stats, damage, battle engine,
                    default movesets, baseline players, matchups, mistake review
                        │  read-only tools
                        v
agents (LLM): Research, Team Composition, Team Optimization, Supervisor, Battle Strategy,
              Opponent Analysis, Battle Evaluation
                        │  output re-checked by code
                        v
CLI (pokeverse …), REST API (FastAPI; catalog endpoints so far) and evaluations
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
│   ├── model.py           # FrozenModel: shared frozen, strict pydantic base
│   ├── paths.py           # default_db_path (POKEVERSE_DB / XDG data dir)
│   ├── cli.py             # Typer app; `pokeverse` console script
│   ├── api/
│   │   ├── app.py         # create_app, app, catalog provider, error → HTTP mapping, /health
│   │   └── catalog.py     # /pokemon, /pokemon/{id}, /pokemon/{id}/learnset, /moves/{id}
│   ├── agents/
│   │   ├── answers.py     # PokedexAnswer + its strict JSON Schema
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
    ├── api/               # TestClient over a temp DB and a mocked PokéAPI
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
| REST API | `pokeverse.api` | FastAPI app (`create_app(catalogs=None)`; module-level `app` for uvicorn). The catalog is injected as a provider stored on `app.state` (`offline` flag → context manager yielding a `PokemonCatalog`), opened per request in the handler's thread because SQLite connections are per thread; tests swap in their own. `GET /health`; `GET /pokemon` (local catalog only), `/pokemon/{name_or_id}`, `/pokemon/{name_or_id}/learnset`, `/moves/{name_or_id}`, each with `?offline=true`. Identifiers are normalized like agent input; invalid ones → 422 before any lookup. Not in catalog → 404, upstream unavailable → 503 (`{"detail": …}`). Responses are the pydantic models, so the OpenAPI schema (`/docs`, `/openapi.json`) comes from them. Will replace the CLI. |
| CLI | `pokeverse.cli` | Typer app. `pokemon <name|id> [--json] [--offline]`, `move <name|id> [--json] [--offline]`, `learnset <pokemon> [--json] [--offline]`, `moveset <pokemon> [<move>...] [--json] [--offline]` (validates a battler, or shows the default moveset), `damage <attacker> <move> <defender> [--json] [--offline]` (damage range at level 50), `battle --side1 … --side2 … [--player1/2 greedy|random|agent] [--seed] [--runs] [--json] [--offline]` (battles; members `name` or `name:move,move`; `agent` adds the Battle Strategy Agent's decisions and token use, briefed by a pre-battle analysis unless `--no-analysis`), `scout --side1 … --side2 … [--json] [--usage]` (Opponent Analysis Agent report and briefing), `battle-eval [--scenario] [--system] [--seeds] [--seed-start] [--json]` (win rate with 95% CI, mistakes, tokens against greedy; progress on stderr), `battle-feedback [--scenario] [--train] [--test] [--json]` (lessons from training seeds, measured on new seeds) and `list [--json]` over the local catalog (names normalized like agent input: `"Mr. Mime"`, `"Swords Dance"`, `#006`); `ask <question> [--no-tools] [--json]` asks the LLM, which can look Pokémon up via the catalog tool (`--usage` traces tool calls; `--json` prints a validated `PokedexAnswer`). `research <question> [--json] [--usage]` runs the Research Agent and warns on ungrounded claims; `eval [--case ID]` runs the evaluation suite; `team <names…> [--json] [--offline]` analyzes a team; `build "<request>" [--json] [--usage]` runs the Team Composition Agent and prints our own analysis of its team; `advise "<request>" [--optimize auto|always|never] [--json] [--usage]` runs the Supervisor and can show delegations and the supervisor/specialist token split; `optimize <names…> [--goal] [--keep] [--notes] [--json] [--usage]` runs the Team Optimization Agent; `compare [--case] [--system] [--json]` runs the single- vs multi-agent comparison. DB path from `--db`, `POKEVERSE_DB`, or `$XDG_DATA_HOME/pokeverse/catalog.db`. Exit codes: 0 ok, 1 not found, 2 invalid input, 3 upstream unavailable, 4 auth/credentials, 5 eval failures; errors on stderr. |
| Catalog models | `pokeverse.catalog.models` | Immutable, self-validating reference data as frozen, strict pydantic models (`FrozenModel`: no type coercion, no unknown fields): `Pokemon` (slug name, 1–2 types, required `BaseStats`, `learnset` of move slugs), `BaseStats` (six base stats, each 1–255, `total`) and the `PokemonType` enum. `Pokemon.to_dict()` includes `base_stats`; `to_dict(stats=False)` omits them (used for team members, where analysis is type-based); the learnset is never serialized. `Move`: slug name, type, `DamageClass` (physical/special/status), `power` (`None` for status and fixed-damage moves; status moves never have power), `accuracy` (`None` = never misses), `priority` (−7…+5), `pp` (1–40). |
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
| Battlers | `pokeverse.battles` | `Battler`: an immutable Pokémon plus 1–4 distinct moves, each in its learnset and supported by the engine (`is_battle_move`: power-based damage, not in `UNMODELLED_MOVES` — self-KO, recharge, charge-turn, conditional, HP-scaled, self-damaging and non-standard-stat moves). `load_battler(catalog, pokemon, moves)` checks the move count and learnset before fetching move details. |
| Battle stats and damage | `pokeverse.battles.stats`, `pokeverse.battles.damage` | Pure functions. `battle_stats` derives level-50 stats (31 IVs, 0 EVs, neutral nature). `calculate_damage` implements the Gen 6+ formula in Pokémon Showdown's integer order (base damage, critical ×1.5, roll 85–100%, STAB ×1.5 rounded half down, type effectiveness, minimum 1 unless immune); `damage_range` gives min/max without a critical hit; `roll_damage` draws the critical hit (1 in 24) and roll from an injected `random.Random`, so battles can be replayed from a seed. |
| Battle engine | `pokeverse.battles.engine` | Singles battles between two teams of 1–6 battlers as pure transitions over immutable `BattleState` (two `Side`s of `Combatant`s with current HP). `legal_actions` lists `UseMove`/`Switch` choices and every choice is validated against it (`IllegalActionError`). `play_turn`: switches first, then moves by priority, speed and a seeded tie-break; immunity before the accuracy roll; knocked-out battlers do not act. `replace_fainted` handles forced switches. `run_battle` drives two `Player`s (protocol: `choose(state, side, options)`) to a win or a draw at `MAX_TURNS` and returns structured `BattleEvent`s. PP is not tracked. |
| Default movesets | `pokeverse.battles.movesets` | `move_score` (power × accuracy × STAB × matching attack stat); `choose_moveset`: best-scoring move first, then the best moves adding super-effective coverage, one per type; `default_battler` resolves every learnable move through the catalog (fetched once, then cached) and fails rather than choose from a partial learnset. |
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
- Dependencies managed with uv (`uv.lock`). Runtime: Typer, FastAPI, uvicorn, httpx, pydantic, OpenAI SDK, python-dotenv.
- REST API: `uv run uvicorn pokeverse.api:app --reload` (http://127.0.0.1:8000, interactive docs at `/docs`).
- Persistence: local SQLite file, by default `~/.local/share/pokeverse/catalog.db` (outside the repo).
- LLM inference temporarily uses the OpenAI Responses API (default model `gpt-6-luna`, override with `POKEVERSE_MODEL_ID`; `POKEVERSE_REASONING_EFFORT` defaults to `none`, and temperature is only sent when it is `none`); credentials come from `OPENAI_API_KEY`, either exported or read from a git-ignored `.env` in the working directory (exported values win). Network access: PokéAPI client and OpenAI.
