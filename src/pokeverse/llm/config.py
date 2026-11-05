"""LLM configuration, read from environment variables with safe defaults."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MODEL_ID = "us.amazon.nova-lite-v1:0"
DEFAULT_REGION = "us-east-1"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 512


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """Inference settings.

    Credentials are never configured here: boto3 resolves them through its
    standard chain (``AWS_PROFILE``, SSO, environment variables, instance roles).
    """

    model_id: str = DEFAULT_MODEL_ID
    region: str = DEFAULT_REGION
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not 0.0 <= self.temperature <= 1.0:
            raise ValueError("temperature must be between 0.0 and 1.0")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LlmSettings:
        """Build settings from ``POKEVERSE_MODEL_ID`` and ``AWS_REGION``/``AWS_DEFAULT_REGION``."""
        env = os.environ if environ is None else environ
        return cls(
            model_id=env.get("POKEVERSE_MODEL_ID", DEFAULT_MODEL_ID),
            region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or DEFAULT_REGION,
        )
