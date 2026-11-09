"""Shared base for PokéVerse domain models."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Immutable and strict: no type coercion (e.g. "25" is not an int) and no unknown fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


def _non_blank(text: str) -> str:
    if not text.strip():
        raise ValueError("must not be blank")
    return text


NonBlank = Annotated[str, AfterValidator(_non_blank)]
