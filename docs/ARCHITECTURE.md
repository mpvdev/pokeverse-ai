# Architecture

> Describes what is **actually implemented**. Planned architecture lives in [CLAUDE.md](../CLAUDE.md).

## Current State (Phase 1 start)

```text
pokeverse-ai/
├── src/pokeverse/
│   ├── __main__.py        # `python -m pokeverse` entry point
│   ├── cli.py             # Typer app; `pokeverse` console script
│   ├── agents/
│   │   └── tools.py       # get_pokemon catalog tool + input normalization
│   └── catalog/
│       ├── __init__.py    # Public catalog API (re-exports Pokemon)
│       ├── models.py      # Pokemon, PokemonType, parse_identifier
│       ├── pokeapi.py     # PokéAPI HTTP client + payload mapping
│       ├── repository.py  # SQLite persistence
│       └── service.py     # Local-first PokemonCatalog
│   └── llm/
│       ├── config.py      # LlmSettings (model id, temperature, max tokens, reasoning effort)
│       ├── tools.py       # Provider-neutral Tool / ToolCall
│       └── openai.py      # OpenAIChat (Responses API, tool loop) + LLM error types
└── tests/
    ├── test_cli.py
    ├── agents/
    │   └── test_tools.py
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
| CLI | `pokeverse.cli` | Typer app. `pokemon <name|id> [--json] [--offline]` and `list [--json]` over the local catalog; `ask <question> [--no-tools]` asks the LLM, which can look Pokémon up via the catalog tool (`--usage` traces tool calls). DB path from `--db`, `POKEVERSE_DB`, or `$XDG_DATA_HOME/pokeverse/catalog.db`. Exit codes: 0 ok, 1 not found, 2 invalid input, 3 upstream unavailable, 4 auth/credentials; errors on stderr. |
| Catalog models | `pokeverse.catalog.models` | Immutable, self-validating reference data: `Pokemon` (slug name, 1–2 types) and the `PokemonType` enum. |
| PokéAPI client | `pokeverse.catalog.pokeapi` | Fetches a Pokémon by name/id, maps the payload to `Pokemon`, and translates HTTP/network failures into typed `PokeApiError` subclasses. Import-only; not a runtime dependency. |
| Repository | `pokeverse.catalog.repository` | `SqlitePokemonRepository`: tables `pokemon` and `pokemon_type` (slot-ordered), schema version in `PRAGMA user_version`, atomic upserts. |
| Catalog service | `pokeverse.catalog.service` | `PokemonCatalog`: reads locally first; on a miss imports via a `PokemonSource` (e.g. `PokeApiClient`) and stores the result. Raises `PokemonNotInCatalogError` or `UpstreamUnavailableError`; cached data never depends on upstream. |
| LLM client | `pokeverse.llm` | `OpenAIChat.complete()` sends a Responses API request and returns a `Completion` (text, status, summed token usage, latency, `tool_calls`). With `tools`, it runs a bounded loop (default 5 rounds): execute each `function_call`, send back the model output plus `function_call_output`, repeat until a text reply. Tools are provider-neutral `Tool` objects sent in strict mode. Errors mapped to `LlmAuthError`, `LlmUnavailableError`, `LlmRequestError`. |
| Catalog tools | `pokeverse.agents.tools` | `make_catalog_tools(catalog)` returns the read-only `get_pokemon` tool. Normalizes model input (`"Mr. Mime"` → `mr-mime`, `"#025"` → 25), returns `Pokemon.to_dict()`, and reports catalog failures as `{"error", "message"}` data so the model can explain them. |

### Runtime

- Python 3.15, packaged with setuptools (`src/` layout).
- Dependencies managed with uv (`uv.lock`). Runtime: Typer, httpx, OpenAI SDK, python-dotenv.
- Persistence: local SQLite file, by default `~/.local/share/pokeverse/catalog.db` (outside the repo).
- LLM inference temporarily uses the OpenAI Responses API (default model `gpt-6-luna`, override with `POKEVERSE_MODEL_ID`; `POKEVERSE_REASONING_EFFORT` defaults to `none`, and temperature is only sent when it is `none`); credentials come from `OPENAI_API_KEY`, either exported or read from a git-ignored `.env` in the working directory (exported values win). Network access: PokéAPI client and OpenAI.

## Target Shape for Phase 1

Implemented up to tool calling; structured outputs and the Research Agent are planned:

```text
PokéAPI ──> PokéAPI client ──> normalization ──> local catalog (SQLite)
                                                       │
                                          catalog interface (repository)
                                                       │
                              Research Agent (LLM + tools) ──> CLI
```

Key principle: everything to the left of the agent is deterministic, testable code. The LLM only reads the catalog through tools; it never writes reference data.
