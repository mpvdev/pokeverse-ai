# Progress

## Current Phase

**Phase 2 — Multi-Agent Trainer System** (not started). Phase 1 is complete on branch `phase-1`.

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

## Next Up

- Phase 2 — Multi-Agent Trainer System: Supervisor Agent, specialized agents, delegation, shared context, multi- vs single-agent evaluation.
- Known gap found by the live run: the agent answers type-effectiveness questions from memory and got one wrong (said Ghost/Poison Gengar is not weak to Psychic). Type effectiveness should be a deterministic catalog tool, not LLM recall; add an eval case for it.

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
```
