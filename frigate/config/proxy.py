from typing import Optional

from pydantic import Field, field_validator, model_validator

from .base import FrigateBaseModel
from .env import EnvString

__all__ = ["ProxyConfig", "HeaderMappingConfig"]


class HeaderMappingConfig(FrigateBaseModel):
    user: str = Field(
        default=None,
        title="User header",
        description="Header containing the authenticated username provided by the upstream proxy.",
    )
    role: str = Field(
        default=None,
        title="Role header",
        description="Header containing the authenticated user's role or groups from the upstream proxy.",
    )
    role_map: Optional[dict[str, list[str]]] = Field(
        default_factory=dict,
        title=("Role mapping"),
        description="Map upstream group values to Frigate roles (for example map admin groups to the admin role).",
    )


class ProxyConfig(FrigateBaseModel):
    auth_enabled: bool = Field(
        default=False,
        title="Enable proxy authentication",
        description="Allow a trusted upstream authentication proxy to authenticate users while native Frigate authentication remains enabled.",
    )
    header_map: HeaderMappingConfig = Field(
        default_factory=HeaderMappingConfig,
        title="Header mapping",
        description="Map incoming proxy headers to Frigate user and role fields for proxy-based auth.",
    )
    logout_url: Optional[str] = Field(
        default=None,
        title="Logout URL",
        description="URL to redirect users to when logging out via the proxy.",
    )
    auth_secret: Optional[EnvString] = Field(
        default=None,
        title="Proxy secret",
        description="Secret checked against X-Proxy-Secret to verify trusted proxies; required when proxy authentication is enabled alongside native authentication.",
    )
    default_role: Optional[str] = Field(
        default="viewer",
        title="Default role",
        description="Default role assigned to proxy-authenticated users when no role mapping applies (admin or viewer).",
    )
    separator: Optional[str] = Field(
        default=",",
        title="Separator character",
        description="Character used to split multiple values provided in proxy headers.",
    )

    @field_validator("separator", mode="before")
    @classmethod
    def validate_separator_length(cls, v):
        if v is not None and len(v) != 1:
            raise ValueError("Separator must be exactly one character")
        return v

    @model_validator(mode="after")
    def validate_proxy_authentication(self):
        if not self.auth_enabled:
            return self

        if not self.header_map.user or not self.header_map.user.strip():
            raise ValueError(
                "proxy.header_map.user must be configured when proxy.auth_enabled is true"
            )

        if not self.auth_secret or not str(self.auth_secret).strip():
            raise ValueError(
                "proxy.auth_secret must be configured when proxy.auth_enabled is true"
            )

        return self
