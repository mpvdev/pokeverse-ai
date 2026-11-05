# Architecture

> Describes what is **actually implemented**. Planned architecture lives in [CLAUDE.md](../CLAUDE.md).

## Current State (Phase 1 start)

```text
pokeverse-ai/
├── src/pokeverse/
│   ├── __main__.py        # `python -m pokeverse` entry point
│   ├── cli.py             # Typer app; `pokeverse` console script
│   └── catalog/
│       ├── __init__.py    # Public catalog API (re-exports Pokemon)
│       ├── models.py      # Pokemon, PokemonType, parse_identifier
│       ├── pokeapi.py     # PokéAPI HTTP client + payload mapping
│       ├── repository.py  # SQLite persistence
│       └── service.py     # Local-first PokemonCatalog
│   └── llm/
│       ├── config.py      # LlmSettings (model id, region, temperature, max tokens)
│       └── bedrock.py     # BedrockChat (Converse API) + LLM error types
└── tests/
    ├── test_cli.py
    └── catalog/
        ├── fixtures/pokeapi/   # recorded PokéAPI responses
        ├── test_models.py
        ├── test_pokeapi.py
        ├── test_repository.py
        └── test_service.py
    └── llm/
        ├── test_config.py
        └── test_bedrock.py   # botocore Stubber, no network
```

### Components

| Component | Module | Responsibility |
|-----------|--------|----------------|
| CLI | `pokeverse.cli` | Typer app. `pokemon <name|id> [--json] [--offline]` and `list [--json]` over the local catalog; `ask <question>` sends a raw prompt to the LLM. DB path from `--db`, `POKEVERSE_DB`, or `$XDG_DATA_HOME/pokeverse/catalog.db`. Exit codes: 0 ok, 1 not found, 2 invalid input, 3 upstream unavailable, 4 auth/credentials; errors on stderr. |
| Catalog models | `pokeverse.catalog.models` | Immutable, self-validating reference data: `Pokemon` (slug name, 1–2 types) and the `PokemonType` enum. |
| PokéAPI client | `pokeverse.catalog.pokeapi` | Fetches a Pokémon by name/id, maps the payload to `Pokemon`, and translates HTTP/network failures into typed `PokeApiError` subclasses. Import-only; not a runtime dependency. |
| Repository | `pokeverse.catalog.repository` | `SqlitePokemonRepository`: tables `pokemon` and `pokemon_type` (slot-ordered), schema version in `PRAGMA user_version`, atomic upserts. |
| Catalog service | `pokeverse.catalog.service` | `PokemonCatalog`: reads locally first; on a miss imports via a `PokemonSource` (e.g. `PokeApiClient`) and stores the result. Raises `PokemonNotInCatalogError` or `UpstreamUnavailableError`; cached data never depends on upstream. |
| LLM client | `pokeverse.llm` | `BedrockChat.complete()` sends a single-turn Converse request and returns a `Completion` (text, stop reason, token usage, latency). Errors mapped to `LlmAuthError`, `LlmUnavailableError`, `LlmRequestError`. Not yet connected to the catalog. |

### Runtime

- Python 3.15, packaged with setuptools (`src/` layout).
- Dependencies managed with uv (`uv.lock`). Runtime: Typer, httpx, boto3.
- Persistence: local SQLite file, by default `~/.local/share/pokeverse/catalog.db` (outside the repo).
- LLM inference via Amazon Bedrock (default model `us.amazon.nova-lite-v1:0`, region `us-east-1`); credentials from the standard AWS chain. Network access: PokéAPI client and Bedrock.

## Target Shape for Phase 1

Implemented up to the CLI lookup; the Research Agent is planned:

```text
PokéAPI ──> PokéAPI client ──> normalization ──> local catalog (SQLite)
                                                       │
                                          catalog interface (repository)
                                                       │
                              Research Agent (LLM + tools) ──> CLI
```

Key principle: everything to the left of the agent is deterministic, testable code. The LLM only reads the catalog through tools; it never writes reference data.
