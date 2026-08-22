import os
from typing import Dict, List, Optional

from pydantic import Field, field_validator, model_validator

from .base import FrigateBaseModel
from .env import EnvString

__all__ = ["AuthConfig", "OidcConfig"]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class OidcConfig(FrigateBaseModel):
    enabled: bool = Field(
        default_factory=lambda: _env_bool("FRIGATE_OIDC_ENABLED"),
        title="Enable OpenID Connect",
        description="Show an optional OpenID Connect login alongside native Frigate login.",
    )
    provider_name: str = Field(
        default_factory=lambda: os.environ.get("FRIGATE_OIDC_PROVIDER_NAME", "SSO"),
        title="Provider name",
        description="Name displayed on the login button, for example Authentik.",
        min_length=1,
        max_length=50,
    )
    issuer_url: Optional[EnvString] = Field(
        default_factory=lambda: os.environ.get("FRIGATE_OIDC_ISSUER_URL"),
        title="Issuer URL",
        description="OpenID Connect issuer URL used for provider discovery.",
    )
    client_id: Optional[EnvString] = Field(
        default_factory=lambda: os.environ.get("FRIGATE_OIDC_CLIENT_ID"),
        title="Client ID",
        description="OpenID Connect client ID.",
    )
    client_secret: Optional[EnvString] = Field(
        default_factory=lambda: os.environ.get("FRIGATE_OIDC_CLIENT_SECRET"),
        title="Client secret",
        description="OpenID Connect client secret. Docker secrets and FRIGATE_ placeholders are supported.",
    )
    redirect_uri: Optional[EnvString] = Field(
        default_factory=lambda: os.environ.get("FRIGATE_OIDC_REDIRECT_URI"),
        title="Redirect URI",
        description="Public callback URI. If omitted, Frigate derives it from the incoming request.",
    )
    scopes: List[str] = Field(
        default=["openid", "profile", "email"],
        title="Scopes",
        description="OpenID Connect scopes requested from the provider.",
    )
    username_claim: str = Field(
        default="preferred_username",
        title="Username claim",
        description="ID token claim mapped to the Frigate username.",
        min_length=1,
    )
    auto_create_users: bool = Field(
        default=False,
        title="Automatically create users",
        description="Create unknown OIDC users in Frigate with the configured default role.",
    )
    default_role: str = Field(
        default="viewer",
        title="Default role",
        description="Frigate role assigned when an OIDC user is created automatically.",
    )

    @model_validator(mode="after")
    def validate_oidc(self):
        if self.enabled and (not self.issuer_url or not self.client_id):
            raise ValueError(
                "OIDC issuer_url and client_id are required when OIDC is enabled."
            )
        if "openid" not in self.scopes:
            raise ValueError("OIDC scopes must include 'openid'.")
        return self


class AuthConfig(FrigateBaseModel):
    enabled: bool = Field(
        default=True,
        title="Enable authentication",
        description="Enable native authentication for the Frigate UI.",
    )
    reset_admin_password: bool = Field(
        default=False,
        title="Reset admin password",
        description="If true, reset the admin user's password on startup and print the new password in logs.",
    )
    cookie_name: str = Field(
        default="frigate_token",
        title="JWT cookie name",
        description="Name of the cookie used to store the JWT token for native authentication.",
        pattern=r"^[a-z_]+$",
    )
    cookie_secure: bool = Field(
        default=False,
        title="Secure cookie flag",
        description="Set the secure flag on the auth cookie; should be true when using TLS.",
    )
    session_length: int = Field(
        default=86400,
        title="Session length",
        description="Session duration in seconds for JWT-based sessions.",
        ge=60,
    )
    refresh_time: int = Field(
        default=1800,
        title="Session refresh window",
        description="When a session is within this many seconds of expiring, refresh it back to full length.",
        ge=30,
    )
    failed_login_rate_limit: Optional[str] = Field(
        default=None,
        title="Failed login limits",
        description="Rate limiting rules for failed login attempts to reduce brute-force attacks.",
    )
    trusted_proxies: list[str] = Field(
        default=[],
        title="Trusted proxies",
        description="List of trusted proxy IPs used when determining client IP for rate limiting.",
    )
    # As of Feb 2023, OWASP recommends 600000 iterations for PBKDF2-SHA256
    hash_iterations: int = Field(
        default=600000,
        title="Hash iterations",
        description="Number of PBKDF2-SHA256 iterations to use when hashing user passwords.",
    )
    roles: Dict[str, List[str]] = Field(
        default_factory=dict,
        title="Role mappings",
        description="Map roles to camera lists. An empty list grants access to all cameras for the role.",
    )
    admin_first_time_login: Optional[bool] = Field(
        default=False,
        title="First-time admin flag",
        description=(
            "When true the UI may show a help link on the login page informing users how to sign in after an admin password reset. "
        ),
    )
    oidc: OidcConfig = Field(
        default_factory=OidcConfig,
        title="OpenID Connect",
        description="Optional native OpenID Connect login configuration.",
    )

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: Dict[str, List[str]]) -> Dict[str, List[str]]:
        # Ensure role names are valid (alphanumeric with underscores)
        for role in v.keys():
            if not role.replace("_", "").isalnum():
                raise ValueError(
                    f"Invalid role name '{role}'. Must be alphanumeric with underscores."
                )

        # Ensure 'admin' and 'viewer' are not used as custom role names
        reserved_roles = {"admin", "viewer"}
        if v.keys() & reserved_roles:
            raise ValueError(
                f"Reserved roles {reserved_roles} cannot be used as custom roles."
            )

        # Ensure no role has an empty camera list
        for role, allowed_cameras in v.items():
            if not allowed_cameras:
                raise ValueError(
                    f"Role '{role}' has no cameras assigned. Custom roles must have at least one camera."
                )

        return v

    @model_validator(mode="after")
    def ensure_default_roles(self):
        # Ensure admin and viewer are never overridden
        self.roles["admin"] = []
        self.roles["viewer"] = []

        if self.oidc.enabled and not self.enabled:
            raise ValueError(
                "OpenID Connect cannot be enabled while native authentication is disabled."
            )

        return self
