from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from typing_extensions import Self

from .base import FrigateBaseModel
from .env import FRIGATE_ENV_VARS, EnvString


class ModelTrainerConfig(FrigateBaseModel):
    enabled: bool = Field(
        default=False,
        title="Enable model trainer submissions",
        description="Allow Frigate to submit images to the configured model training portal.",
    )
    url: EnvString | None = Field(
        default_factory=lambda: FRIGATE_ENV_VARS.get("FRIGATE_MODEL_TRAINER_URL"),
        validate_default=True,
        title="Model trainer URL",
        description="Base URL of the model training portal.",
    )
    api_key: EnvString | None = Field(
        default_factory=lambda: FRIGATE_ENV_VARS.get("FRIGATE_MODEL_TRAINER_API_KEY"),
        validate_default=True,
        title="Model trainer API key",
        description="Bearer token for the model training portal. Docker secrets and FRIGATE_ placeholders are supported.",
    )

    @model_validator(mode="after")
    def validate_enabled_settings(self) -> Self:
        if self.enabled and not self.url:
            raise ValueError(
                "model_trainer.url is required when model_trainer is enabled"
            )
        if self.enabled and not self.api_key:
            raise ValueError(
                "model_trainer.api_key is required when model_trainer is enabled"
            )
        if self.url:
            try:
                parsed_url = urlsplit(self.url)
                valid_absolute_url = (
                    parsed_url.scheme in ("http", "https")
                    and bool(parsed_url.netloc)
                    and bool(parsed_url.hostname)
                    and parsed_url.username is None
                    and parsed_url.password is None
                    and not parsed_url.query
                    and not parsed_url.fragment
                    and "?" not in self.url
                    and "#" not in self.url
                )
                # Accessing .port also rejects malformed port strings.
                parsed_port = parsed_url.port
                if parsed_url.netloc.endswith(":") and parsed_port is None:
                    valid_absolute_url = False
            except ValueError:
                valid_absolute_url = False
            if not valid_absolute_url:
                raise ValueError(
                    "model_trainer.url must be an absolute HTTP(S) URL without "
                    "userinfo, query, or fragment"
                )
        return self


ImageSubmissionApi = Literal["plus", "model_trainer"]
