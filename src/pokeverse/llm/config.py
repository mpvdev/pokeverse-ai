"""LLM configuration, read from environment variables with safe defaults."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MODEL_ID = "gpt-6-luna"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 512
DEFAULT_REASONING_EFFORT = "none"
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """Inference settings.

    Credentials are never configured here: the OpenAI client reads
    ``OPENAI_API_KEY`` from the environment.
    """

    model_id: str = DEFAULT_MODEL_ID
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    reasoning_effort: str = DEFAULT_REASONING_EFFORT

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not 0.0 <= self.temperature <= 1.0:
            raise ValueError("temperature must be between 0.0 and 1.0")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(f"reasoning_effort must be one of {', '.join(REASONING_EFFORTS)}")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LlmSettings:
        """Build settings from ``POKEVERSE_MODEL_ID`` and ``POKEVERSE_REASONING_EFFORT``."""
        env = os.environ if environ is None else environ
        return cls(
            model_id=env.get("POKEVERSE_MODEL_ID", DEFAULT_MODEL_ID),
            reasoning_effort=env.get("POKEVERSE_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        )
