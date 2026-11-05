import pytest

from pokeverse.llm import LlmSettings
from pokeverse.llm.config import DEFAULT_MODEL_ID


def test_defaults() -> None:
    settings = LlmSettings()

    assert settings.model_id == DEFAULT_MODEL_ID == "gpt-6-luna"


def test_from_env_uses_defaults_when_unset() -> None:
    assert LlmSettings.from_env({}) == LlmSettings()


def test_from_env_reads_overrides() -> None:
    settings = LlmSettings.from_env(
        {"POKEVERSE_MODEL_ID": "gpt-6.1-sol", "POKEVERSE_REASONING_EFFORT": "low"}
    )

    assert settings.model_id == "gpt-6.1-sol"
    assert settings.reasoning_effort == "low"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_id": " "},
        {"temperature": -0.1},
        {"temperature": 1.1},
        {"max_tokens": 0},
        {"reasoning_effort": "minimal"},
    ],
)
def test_invalid_settings_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LlmSettings(**kwargs)  # type: ignore[arg-type]
