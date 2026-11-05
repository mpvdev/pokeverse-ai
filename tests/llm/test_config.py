import pytest

from pokeverse.llm import LlmSettings
from pokeverse.llm.config import DEFAULT_MODEL_ID, DEFAULT_REGION


def test_defaults() -> None:
    settings = LlmSettings()

    assert settings.model_id == DEFAULT_MODEL_ID == "us.amazon.nova-lite-v1:0"
    assert settings.region == DEFAULT_REGION == "us-east-1"


def test_from_env_uses_defaults_when_unset() -> None:
    assert LlmSettings.from_env({}) == LlmSettings()


def test_from_env_reads_overrides() -> None:
    settings = LlmSettings.from_env(
        {"POKEVERSE_MODEL_ID": "us.amazon.nova-micro-v1:0", "AWS_REGION": "us-west-2"}
    )

    assert settings.model_id == "us.amazon.nova-micro-v1:0"
    assert settings.region == "us-west-2"


def test_from_env_falls_back_to_aws_default_region() -> None:
    assert LlmSettings.from_env({"AWS_DEFAULT_REGION": "eu-west-1"}).region == "eu-west-1"


@pytest.mark.parametrize(
    "kwargs",
    [{"model_id": " "}, {"temperature": -0.1}, {"temperature": 1.1}, {"max_tokens": 0}],
)
def test_invalid_settings_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LlmSettings(**kwargs)  # type: ignore[arg-type]
