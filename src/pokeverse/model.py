"""Shared base for PokéVerse domain models."""

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Immutable and strict: no type coercion (e.g. "25" is not an int) and no unknown fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
