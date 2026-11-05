# Progress

## Current Phase

**Phase 1 — Intelligent Pokédex** (branch `phase-1`)

## Completed

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

- [x] Step 5: first LLM call — `pokeverse.llm` (`BedrockChat` over the Bedrock Converse API, Amazon Nova Lite), `pokeverse ask` with `--system`, `--temperature`, `--max-tokens`, `--usage`.

## Next Up

- **Paused:** waiting for Amazon Bedrock access on the new AWS SSO account. Then verify step 5 live (`aws sso login && uv run pytest -m bedrock`).
- Step 6: tool calling (catalog lookup as a tool).

## Running Locally

```bash
uv sync                          # create .venv and install from uv.lock
uv run pytest                    # offline tests
uv run pytest -m network         # opt-in live PokéAPI tests
uv run pytest -m bedrock         # opt-in live Bedrock tests (needs AWS credentials, costs money)
uv run ruff check . && uv run ruff format --check .
uv run pokeverse --version
uv run pokeverse pokemon pikachu    # uses ~/.local/share/pokeverse/catalog.db
uv run pokeverse list
aws sso login && uv run pokeverse ask "What type is Pikachu?" --usage
```
