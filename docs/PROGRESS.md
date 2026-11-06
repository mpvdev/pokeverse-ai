# Progress

## Current Phase

**Phase 2 — Multi-Agent Trainer System** (branch `phase-2`). Phase 1 is complete on branch `phase-1`.

## Completed

### Phase 1 — Intelligent Pokédex (branch `phase-1`)

Deliverable: a CLI-based intelligent Pokédex. `pokeverse research` answers Pokémon questions with a tool-using, structured-output agent grounded in a local, outage-tolerant catalog; `pokeverse eval` measures it.

### Phase 0 — Repository Foundation (merged in #1)

- [x] Repository conventions and `.gitignore`
- [x] Python package (`src/pokeverse`) with `pyproject.toml`
- [x] Typer CLI with welcome message and `--version`
- [x] `Pokemon` domain model with validation
- [x] pytest + ruff conventions
- [x] Project guidance (`CLAUDE.md`) and docs skeleton
- [x] Dependency management: uv

## Phase 1 Plan

Each step is a small change implemented by the assistant and reviewed by the developer.

1. **Harden the domain model** — normalize names/types, stricter validation, fuller tests.
2. **PokéAPI client** — fetch one Pokémon, map the response to `Pokemon`; timeouts and errors handled; tests use recorded fixtures, no live network.
3. **Local catalog** — SQLite-backed repository behind a small interface (`get`, `save`, `list`); read-through cache over the client.
4. **CLI lookup** — `pokeverse pokemon <name>` reading from the catalog, JSON output option.
5. **First LLM call** — plain inference from the CLI; learn prompts, tokens, temperature.
6. **Tool calling** — expose catalog lookup as a tool; the model answers using real data.
7. **Structured outputs** — validated, typed responses from the model.
8. **Pokémon Research Agent** — combine the above into the first agent; add basic evaluation cases.

### Phase 1 progress

- [x] Step 1: harden the `Pokemon` model — `PokemonType` enum, slug names, 1–2 distinct types, full rejection-path tests, version test reads installed metadata.

- [x] Step 2: PokéAPI client — `PokeApiClient.fetch_pokemon`, `parse_pokemon`, typed errors, fixture-based tests, opt-in live test.

- [x] Step 3: local catalog — `SqlitePokemonRepository` (stdlib sqlite3, versioned schema) and local-first `PokemonCatalog` that imports from PokéAPI on a miss and serves cached data during outages.

- [x] Step 4: CLI lookup — `pokeverse pokemon <name|id> [--json] [--offline]`, `pokeverse list [--json]`, `--db` / `POKEVERSE_DB`, distinct exit codes.

- [x] Step 5: first LLM call — `pokeverse.llm` (`OpenAIChat` over the Responses API, GPT-6 Luna), `pokeverse ask` with `--system`, `--temperature`, `--max-tokens`, `--usage`. Verified live.

- [x] Step 6: tool calling — provider-neutral `Tool`/`ToolCall`, bounded tool loop in `OpenAIChat`, read-only `get_pokemon` catalog tool (`pokeverse.agents.tools`), `pokeverse ask` uses it by default (`--no-tools` to compare, `--usage` traces calls). Verified live.

- [x] Step 7: structured outputs — provider-neutral `OutputSchema`, strict `text.format` JSON Schema in `OpenAIChat` (parsed into `Completion.data`; truncation and refusals raise `LlmRequestError`), self-validating `PokedexAnswer` (`answer`, `pokemon` slugs, `confidence`), `pokeverse ask --json`. Verified live.

- [x] Step 8: Pokémon Research Agent — `ResearchAgent` (fixed system prompt + catalog tool + `PokedexAnswer` schema) returning a `ResearchResult` with a deterministic grounding check (claimed Pokémon must appear in a successful tool result); `pokeverse.evals` with 7 cases and deterministic checks (expected Pokémon, required facts, tool use, grounding, confidence); `pokeverse research [--json] [--usage]` and `pokeverse eval [--case ID]` (exit 5 on failures). Live baseline on `gpt-5.6-terra`, effort `low`: 7/7 passed, tool use 7/7, 5,692 tokens, ~4.0 s average latency.

## Phase 2 Plan (proposed; revise as we learn)

Deliverable: a multi-agent Pokémon team advisor.

1. **Type matchups as a deterministic tool** — close the Phase 1 gap; team building needs it.
2. **Team model and validation** — a `Team` domain model (1–6 Pokémon, repeats allowed) and deterministic team analysis (shared weaknesses, uncovered types).
3. **Team Composition Agent** — builds a team from user constraints, as a structured, validated `TeamProposal`.
4. **Supervisor Agent and delegation** — routes a request to the Research or Team Composition agent (specialists exposed to the supervisor as tools).
5. **Shared context and handoffs** — one task record passed between agents, with a trace of who did what.
6. **Team Optimization Agent** — critiques a proposal using team analysis and suggests swaps.
7. **Evaluation: multi- vs single-agent** — same tasks, compare validity, grounding, tokens and latency.
8. **`pokeverse advise` CLI** — the Phase 2 deliverable end to end.

### Phase 2 progress

- [x] Step 1: type matchups — hard-coded Gen 6+ chart in `pokeverse.catalog.type_chart` (`effectiveness`, `defensive_profile`), verified row by row against PokéAPI by an opt-in network test; `get_type_matchups` catalog tool; Research Agent prompt forbids computing matchups from memory; grounding also counts Pokémon returned by the matchup tool. Evals: 3 matchup cases with `required_tools`; the unknown-Pokémon case now checks for invented types (`must_not_mention`) instead of self-reported confidence. Live: 10/10 passed, tool use 10/10, 11,746 tokens (~1.2k per question, up from ~0.84k: every request now carries two tool definitions), ~3.8 s average latency. The Phase 1 Gengar question is now answered correctly ("Yes, 2×").

- [x] Step 2: team model and analysis — `pokeverse.teams`: immutable `Team` (1–6 Pokémon; the same species may repeat) and deterministic `analyze_team` → `TeamAnalysis` with per-type exposure (weak / resists / immune members), vulnerabilities (≥2 weak members and weak outnumber cover), unresisted attack types, and STAB-only offensive gaps. `pokeverse team <names…> [--json] [--offline]` (size checked before any lookup). Type-based only: no moves, abilities or stats yet.

- [x] Step 3: Team Composition Agent — `TeamCompositionAgent.build(request)` with `get_pokemon`, `get_type_matchups` and a new deterministic `analyze_team` tool (compact analysis, errors as data); strict `TeamProposal` output (members with roles + summary), validated in Python; our code resolves every member through the catalog (invented Pokémon → `LlmRequestError`), runs its own `analyze_team`, and reports `self_checked` (did the agent analyze exactly the final team). `pokeverse build "<request>" [--json] [--usage]`. Live: "balanced team of 6 around Pikachu" → no vulnerabilities, self-checked, routed around two PokéAPI timeouts, ~5.3k tokens / 34 s cold. Known gap: on "4 Fire-types only" it accepted its first draft (one `analyze_team` call) with three Fire/Dragon members, adding an avoidable Dragon vulnerability while calling the weaknesses unavoidable — the target for Step 6 (Team Optimization) and the baseline for Step 7.

- [x] Step 4: Supervisor Agent — `Supervisor.run(request)` exposes the Research and Team Composition agents as tools (`ask_research_agent`, `ask_team_builder`, each taking a self-contained `task`). Specialist failures (`LlmRequestError`, `ValueError`) return to the supervisor as error data; auth/outage errors abort. `SupervisorResult` records the observed delegations (agent, task, output or error, tokens) and splits token usage between supervisor and specialists. `pokeverse advise "<request>" [--json] [--usage]`. Live: research-only (2.3k tokens, 8.5 s), research → team build in sequence (16.6k tokens, 46 s; team builder alone 13k), off-topic declined without delegating (0.35k). Observations for Step 5: specialists do not share findings (the team builder re-derived Garchomp's weaknesses the Research Agent had just found), and the supervisor's task rewriting can widen the question (it asked for generation caveats nobody requested).

- [x] Step 5: shared context and handoffs — `SharedContext` (`pokeverse.agents.context`) collects verified facts from specialists' tool outputs only (Pokémon records, matchup profiles, analyzed team members; errors ignored) and appends them as a "Verified facts" block to the next specialist's task; specialist prompts say to rely on them. Handed-over Pokémon count as grounded for the Research Agent. Each `Delegation` records its `handoff`; results include the context. Supervisor prompt: split combined requests (facts to Research, team to Team Composition) and add no unrequested constraints. `LlmRequestError` now carries the partial `Completion` (usage + tool calls before failure), so failed delegations report real tokens. Team builder prompt: `analyze_team` resolves members itself, so try candidates directly. Benchmark ("Garchomp weaknesses, then a team of 4"): Step 4 16.6k tokens / 46 s → 8.3k / 26.5 s; team builder 13.1k → 5.1k; research task now only the factual question; handoff `garchomp`. Diagnosed along the way: the first run failed after 8 tool rounds because the builder spent two sequential rounds per swap (`get_pokemon` then `analyze_team`) while genuinely revising. Remaining gap: role descriptions are unchecked model prose (it claimed Flying/Steel Corviknight resists Ice; it is neutral) — input for Step 6.

- [x] Step 6: Team Optimization Agent — the model proposes, code decides. `TeamOptimizationAgent.optimize(team, goal, keep, notes)`: the model only *extracts* type claims from the notes (code checks each against the chart, falling back to the catalog for non-members) and proposes up to 3 swaps; code applies them in order and keeps a swap only if `TeamAnalysis.score` (vulnerabilities, members exposed, unresisted, offensive gaps; lower is better) strictly improves, and never removes a `keep` member. New compact `score_team` tool for exploring candidates (the full `analyze_team` made exploration cost 23k tokens for 16 candidates; now 5.2k). Supervisor gets `ask_team_optimizer` (members, goal, keep, notes) and is told to optimize after building and to correct wrong claims; verified facts are passed as a separate block so they are not extracted as claims. `pokeverse optimize <names…> [--goal] [--keep] [--notes] [--json] [--usage]`. Live: Fire-only team score (3,11,11,10) → (2,6,9,8) with 2 accepted swaps, still Fire-only, Dragon vulnerability removed; the Corviknight-resists-Ice claim flagged WRONG (1×); end to end via `advise` the final answer corrects it. Cost: the full research → build → optimize flow took 23.7k tokens / 72 s (optimizer 15.5k) vs 8.3k / 26.5 s without optimizing — the quality/cost trade-off for Step 7 to measure. Known limit: the optimizer's own critique can repeat a claim that code later marks wrong (checks happen after the reply); `goal` constraints like "Fire-only" are enforced only by the model.

- [x] Step 7: multi- vs single-agent evaluation — `GeneralistAgent` (one agent, all tools, `{answer, team}` output) as the baseline; `Supervisor(optimize=False)`; `pokeverse.evals.compare` with 5 fixed tasks scored only by code (required facts, team size, must-include members, type constraints, attack types the team must resist, max vulnerabilities, answer names the produced team); teams taken from observed output and re-analyzed. `pokeverse compare [--case] [--system] [--json]` streams progress and keeps partial results if an outage aborts the run. Results (gpt-5.6-terra, effort low, one run per cell): single 4/5, ~25k tokens; multi 5/5, ~47k; multi+opt 5/5, ~64k. Only the constrained "4 Fire-types, ≤2 vulnerabilities" task separates them: single failed it in both runs, both multi systems pass, multi+opt with the best team. On easy tasks single is as good and 2–4× cheaper; the optimizer added cost without extra passes (its builds already had no vulnerabilities). Found and fixed on the way: the team builder was cut off at 1,500 output tokens on constrained tasks (now 3,000; reasoning counts), and failed delegations were invisible in the comparison (now listed when a run fails; recovered errors don't fail a run). Caveat: one sample per cell — differences in score between runs are partly sampling variance.

## Next Up

- Phase 2, Step 8: `pokeverse advise` end to end — apply the Step 7 findings (run the optimizer only when the built team has vulnerabilities or claims to check) and close the phase.

## Running Locally

```bash
uv sync                          # create .venv and install from uv.lock
uv run pytest                    # offline tests
uv run pytest -m network         # opt-in live PokéAPI tests
uv run pytest -m openai          # opt-in live OpenAI tests (needs OPENAI_API_KEY, costs money)
uv run ruff check . && uv run ruff format --check .
uv run pokeverse --version
uv run pokeverse pokemon pikachu    # uses ~/.local/share/pokeverse/catalog.db
uv run pokeverse list
uv run pokeverse ask "What type is Pikachu?" --usage   # needs OPENAI_API_KEY in .env or the environment
uv run pokeverse ask "What type is Pikachu?" --no-tools --usage   # model answers from memory only
uv run pokeverse ask "What type is Pikachu?" --json              # validated structured answer
uv run pokeverse research "What type is Mr. Mime?" --usage       # Research Agent
uv run pokeverse eval                                            # evaluation suite (live, costs tokens)
uv run pokeverse team charizard blastoise venusaur              # deterministic team analysis
uv run pokeverse build "A balanced team of 6 around Pikachu"    # Team Composition Agent
uv run pokeverse advise "Is Gengar weak to Psychic?" --usage    # Supervisor (delegates)
uv run pokeverse optimize reshiram turtonator gouging-fire volcanion --goal "Fire-only"   # Team Optimization Agent
uv run pokeverse compare --case fire-only                       # single vs multi-agent (live, costly)
```
