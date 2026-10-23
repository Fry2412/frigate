import pytest
from pydantic import ValidationError

from frigate.config import FrigateConfig


def minimal_config(**values):
    return {
        "mqtt": {"host": "mqtt"},
        "cameras": {},
        **values,
    }


def test_model_trainer_is_opt_in_and_plus_remains_submission_default():
    config = FrigateConfig(**minimal_config())

    assert config.model_trainer.enabled is False
    assert config.image_submission_api == "plus"
    assert config.image_submission_client is config.plus_api


def test_model_trainer_config_interpolates_secrets_and_selects_portal(monkeypatch):
    from frigate.config import env

    monkeypatch.setitem(env.FRIGATE_ENV_VARS, "FRIGATE_MODEL_TRAINER_API_KEY", "secret")
    config = FrigateConfig(
        **minimal_config(
            model_trainer={
                "enabled": True,
                "url": "https://trainer.example/",
                "api_key": "{FRIGATE_MODEL_TRAINER_API_KEY}",
            },
            image_submission_api="model_trainer",
        )
    )

    assert config.model_trainer.api_key == "secret"
    assert config.image_submission_client.is_active()
    assert config.image_submission_client.url == "https://trainer.example"


def test_model_trainer_environment_defaults_and_disabled_selection_are_inactive(
    monkeypatch,
):
    from frigate.config import env

    monkeypatch.setitem(env.FRIGATE_ENV_VARS, "FRIGATE_MODEL_TRAINER_URL", "http://env")
    monkeypatch.setitem(
        env.FRIGATE_ENV_VARS, "FRIGATE_MODEL_TRAINER_API_KEY", "env-token"
    )
    config = FrigateConfig(**minimal_config(image_submission_api="model_trainer"))

    assert config.model_trainer.url == "http://env"
    assert config.model_trainer.api_key == "env-token"
    assert config.image_submission_client.is_active() is False


def test_enabled_model_trainer_requires_url_and_key():
    with pytest.raises(ValidationError, match="model_trainer.url is required"):
        FrigateConfig(**minimal_config(model_trainer={"enabled": True}))
    with pytest.raises(ValidationError, match="model_trainer.api_key is required"):
        FrigateConfig(
            **minimal_config(model_trainer={"enabled": True, "url": "http://trainer"})
        )


@pytest.mark.parametrize(
    "url",
    [
        "training-portal:8000",
        "ftp://trainer.example",
        "http://user:password@trainer.example",
        "http://trainer.example?token=secret",
        "http://trainer.example#fragment",
        "http://trainer.example:",
    ],
)
def test_model_trainer_url_must_be_absolute_http_without_credentials_or_suffix(url):
    with pytest.raises(ValidationError, match=r"absolute HTTP\(S\) URL"):
        FrigateConfig(**minimal_config(model_trainer={"url": url}))


@pytest.mark.parametrize(
    "url", ["http://trainer.example", "https://trainer.example/path"]
)
def test_model_trainer_accepts_absolute_http_urls(url):
    config = FrigateConfig(**minimal_config(model_trainer={"url": url}))
    assert config.model_trainer.url == url
