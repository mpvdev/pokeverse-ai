"""Application factory, catalog dependency and error mapping."""

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BeforeValidator, ValidationError

from pokeverse.agents import normalize_identifier
from pokeverse.catalog import (
    CatalogError,
    MoveNotInCatalogError,
    PokemonCatalog,
    PokemonNotInCatalogError,
    SqlitePokemonRepository,
    UpstreamUnavailableError,
    parse_identifier,
)
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.paths import default_db_path

type CatalogProvider = Callable[[], AbstractContextManager[PokemonCatalog]]


def sqlite_catalogs(db_path: Path) -> CatalogProvider:
    """Opens the catalog per use, in the calling thread: SQLite connections are per thread."""

    @contextmanager
    def open_catalog() -> Iterator[PokemonCatalog]:
        with SqlitePokemonRepository(db_path) as repository, PokeApiClient() as client:
            yield PokemonCatalog(repository, client)

    return open_catalog


def get_catalogs(request: Request) -> CatalogProvider:
    return request.app.state.catalogs


def identifier(name_or_id: str) -> str | int:
    """A Pokémon or move name (``Mr. Mime``, ``Swords Dance``) or a numeric id."""
    try:
        return parse_identifier(normalize_identifier(name_or_id))
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


def _name_or_id(value: object) -> str | int:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ValueError("expected a name or a positive id")
    return parse_identifier(normalize_identifier(value) if isinstance(value, str) else value)


def _move_name(value: object) -> str | int:
    name = _name_or_id(value)
    if isinstance(name, int):
        raise ValueError("moves must be given by name")
    return name


NameOrId = Annotated[str | int, BeforeValidator(_name_or_id)]
MoveName = Annotated[str, BeforeValidator(_move_name)]


def message(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(e["msg"].removeprefix("Value error, ") for e in error.errors())
    return str(error)


@contextmanager
def invalid_input() -> Iterator[None]:
    """Domain rule violations (e.g. an unlearnable move) become 422 responses."""
    try:
        yield
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message(error)) from error


Catalogs = Annotated[CatalogProvider, Depends(get_catalogs)]
Identifier = Annotated[str | int, Depends(identifier)]

ERROR_STATUS: dict[type[CatalogError], int] = {
    PokemonNotInCatalogError: status.HTTP_404_NOT_FOUND,
    MoveNotInCatalogError: status.HTTP_404_NOT_FOUND,
    UpstreamUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


async def catalog_error(request: Request, error: Exception) -> JSONResponse:
    code = ERROR_STATUS.get(type(error), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse({"detail": str(error)}, status_code=code)


def create_app(catalogs: CatalogProvider | None = None) -> FastAPI:
    from pokeverse.api.battles import router as battles_router
    from pokeverse.api.catalog import router as catalog_router
    from pokeverse.api.teams import router as teams_router

    app = FastAPI(
        title="PokéVerse AI",
        version=version("pokeverse-ai"),
        description="Unofficial, learning-oriented Pokémon multi-agent platform.",
    )
    db_path = Path(os.environ["POKEVERSE_DB"]) if "POKEVERSE_DB" in os.environ else None
    app.state.catalogs = catalogs or sqlite_catalogs(db_path or default_db_path())
    app.add_exception_handler(CatalogError, catalog_error)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": version("pokeverse-ai")}

    app.include_router(catalog_router)
    app.include_router(teams_router)
    app.include_router(battles_router)
    return app


app = create_app()
