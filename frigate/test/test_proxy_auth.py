import time
import unittest
from types import SimpleNamespace

from joserfc.jwk import OctKey
from pydantic import ValidationError
from starlette.requests import Request

from frigate.api.auth import auth, create_encoded_jwt, logout, resolve_role
from frigate.config import (
    AuthConfig,
    HeaderMappingConfig,
    NetworkingConfig,
    ProxyConfig,
)
from frigate.config.env import FRIGATE_ENV_VARS


class TestProxyRoleResolution(unittest.TestCase):
    def setUp(self):
        self.proxy_config = ProxyConfig(
            auth_secret=None,
            default_role="viewer",
            separator="|",
            header_map=HeaderMappingConfig(
                user="x-remote-user",
                role="x-remote-role",
                role_map={
                    "admin": ["group_admin"],
                    "viewer": ["group_viewer"],
                },
            ),
        )
        self.config_roles = list(["admin", "viewer"])

    def test_role_map_single_group_match(self):
        headers = {"x-remote-role": "group_admin"}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, "admin")

    def test_role_map_multiple_groups(self):
        headers = {"x-remote-role": "group_admin|group_viewer"}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, "admin")

    def test_role_map_or_matching(self):
        config = self.proxy_config
        config.header_map.role_map = {
            "admin": ["group_admin", "group_privileged"],
        }

        # OR semantics: a single matching group should map to the role
        headers = {"x-remote-role": "group_admin"}
        role = resolve_role(headers, config, self.config_roles)
        self.assertEqual(role, "admin")

        headers = {"x-remote-role": "group_admin|group_privileged"}
        role = resolve_role(headers, config, self.config_roles)
        self.assertEqual(role, "admin")

    def test_direct_role_header_with_separator(self):
        config = self.proxy_config
        config.header_map.role_map = None  # disable role_map
        headers = {"x-remote-role": "admin|viewer"}
        role = resolve_role(headers, config, self.config_roles)
        self.assertEqual(role, "admin")

    def test_invalid_role_header(self):
        config = self.proxy_config
        config.header_map.role_map = None
        headers = {"x-remote-role": "notarole"}
        role = resolve_role(headers, config, self.config_roles)
        self.assertEqual(role, config.default_role)

    def test_missing_role_header(self):
        headers = {}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, self.proxy_config.default_role)

    def test_empty_role_header(self):
        headers = {"x-remote-role": ""}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, self.proxy_config.default_role)

    def test_whitespace_groups(self):
        headers = {"x-remote-role": "   | group_admin |   "}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, "admin")

    def test_mixed_valid_and_invalid_groups(self):
        headers = {"x-remote-role": "bogus|group_viewer"}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, "viewer")

    def test_case_insensitive_role_direct(self):
        config = self.proxy_config
        config.header_map.role_map = None
        headers = {"x-remote-role": "AdMiN"}
        role = resolve_role(headers, config, self.config_roles)
        self.assertEqual(role, "admin")

    def test_role_map_no_match_falls_back(self):
        headers = {"x-remote-role": "group_unknown"}
        role = resolve_role(headers, self.proxy_config, self.config_roles)
        self.assertEqual(role, self.proxy_config.default_role)

    def test_custom_role_mapping(self):
        self.proxy_config.header_map.role_map["operator"] = ["group_operator"]
        role = resolve_role(
            {"x-remote-role": "group_operator"},
            self.proxy_config,
            [*self.config_roles, "operator"],
        )
        self.assertEqual(role, "operator")


class TestProxyAuthSecretEnvString(unittest.TestCase):
    def setUp(self):
        self._original_env_vars = dict(FRIGATE_ENV_VARS)

    def tearDown(self):
        FRIGATE_ENV_VARS.clear()
        FRIGATE_ENV_VARS.update(self._original_env_vars)

    def test_auth_secret_env_substitution(self):
        """auth_secret resolves FRIGATE_ env vars via EnvString."""
        FRIGATE_ENV_VARS["FRIGATE_PROXY_SECRET"] = "my_secret_value"
        config = ProxyConfig(auth_secret="{FRIGATE_PROXY_SECRET}")
        self.assertEqual(config.auth_secret, "my_secret_value")

    def test_auth_secret_env_embedded_in_string(self):
        """auth_secret resolves env vars embedded in a larger string."""
        FRIGATE_ENV_VARS["FRIGATE_SECRET_PART"] = "abc123"
        config = ProxyConfig(auth_secret="prefix-{FRIGATE_SECRET_PART}-suffix")
        self.assertEqual(config.auth_secret, "prefix-abc123-suffix")

    def test_auth_secret_plain_string(self):
        """auth_secret accepts a plain string without substitution."""
        config = ProxyConfig(auth_secret="literal_secret")
        self.assertEqual(config.auth_secret, "literal_secret")

    def test_auth_secret_none(self):
        """auth_secret defaults to None."""
        config = ProxyConfig()
        self.assertIsNone(config.auth_secret)

    def test_auth_secret_unknown_var_raises(self):
        """auth_secret raises KeyError for unknown env var references."""
        with self.assertRaises(Exception):
            ProxyConfig(auth_secret="{FRIGATE_NONEXISTENT_VAR}")


class TestHybridProxyConfig(unittest.TestCase):
    def test_auth_enabled_defaults_to_false(self):
        self.assertFalse(ProxyConfig().auth_enabled)

    def test_hybrid_requires_user_header(self):
        with self.assertRaises(ValidationError):
            ProxyConfig(auth_enabled=True, auth_secret="secret")

    def test_hybrid_requires_auth_secret(self):
        with self.assertRaises(ValidationError):
            ProxyConfig(
                auth_enabled=True,
                header_map=HeaderMappingConfig(user="x-authentik-username"),
            )

    def test_hybrid_accepts_complete_configuration(self):
        config = ProxyConfig(
            auth_enabled=True,
            auth_secret="secret",
            header_map=HeaderMappingConfig(user="x-authentik-username"),
        )
        self.assertTrue(config.auth_enabled)


class TestHybridProxyAuthentication(unittest.TestCase):
    def setUp(self):
        self.jwt_key = OctKey.import_key(b"test-secret-with-sufficient-length")
        self.native_auth = AuthConfig(enabled=True)
        self.hybrid_proxy = ProxyConfig(
            auth_enabled=True,
            auth_secret="proxy-secret",
            separator="|",
            header_map=HeaderMappingConfig(
                user="x-authentik-username",
                role="x-authentik-groups",
                role_map={
                    "admin": ["frigate-admin"],
                    "viewer": ["frigate-viewer"],
                },
            ),
        )

    def request(self, headers=None, auth_config=None, proxy_config=None):
        app = SimpleNamespace(
            frigate_config=SimpleNamespace(
                auth=auth_config or self.native_auth,
                proxy=proxy_config or self.hybrid_proxy,
                networking=NetworkingConfig(),
            ),
            jwt_token=self.jwt_key,
        )
        raw_headers = [
            (key.lower().encode(), value.encode())
            for key, value in (headers or {}).items()
        ]
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/auth",
                "query_string": b"",
                "headers": raw_headers,
                "scheme": "https",
                "server": ("frigate.test", 8971),
                "client": ("127.0.0.1", 1234),
                "app": app,
            }
        )

    def jwt_header(self, user="native-admin", role="admin"):
        token = create_encoded_jwt(user, role, int(time.time()) + 3600, self.jwt_key)
        return {"authorization": f"Bearer {token}"}

    def test_internal_port_bypass_is_unchanged(self):
        response = auth(self.request({"x-server-port": "5000"}))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["remote-user"], "anonymous")
        self.assertEqual(response.headers["remote-role"], "admin")
        self.assertEqual(response.headers["remote-auth-source"], "internal")

    def test_native_fallback_without_proxy_identity(self):
        response = auth(self.request(self.jwt_header()))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["remote-user"], "native-admin")
        self.assertEqual(response.headers["remote-auth-source"], "jwt")

    def test_missing_proxy_identity_and_jwt_is_unauthorized(self):
        response = auth(self.request())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["location"], "/login")

    def test_valid_proxy_identity_wins_over_jwt(self):
        headers = {
            **self.jwt_header(),
            "x-authentik-username": "dominik",
            "x-authentik-groups": "frigate-viewer",
            "x-proxy-secret": "proxy-secret",
        }
        response = auth(self.request(headers))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["remote-user"], "dominik")
        self.assertEqual(response.headers["remote-role"], "viewer")
        self.assertEqual(response.headers["remote-auth-source"], "proxy")

    def test_valid_proxy_identity_wins_over_jwt_cookie(self):
        token = create_encoded_jwt(
            "native-admin", "admin", int(time.time()) + 3600, self.jwt_key
        )
        response = auth(
            self.request(
                {
                    "cookie": f"frigate_token={token}",
                    "x-authentik-username": "dominik",
                    "x-authentik-groups": "frigate-viewer",
                    "x-proxy-secret": "proxy-secret",
                }
            )
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["remote-user"], "dominik")
        self.assertEqual(response.headers["remote-role"], "viewer")

    def test_proxy_admin_role_has_precedence(self):
        response = auth(
            self.request(
                {
                    "x-authentik-username": "dominik",
                    "x-authentik-groups": "frigate-viewer|frigate-admin",
                    "x-proxy-secret": "proxy-secret",
                }
            )
        )
        self.assertEqual(response.headers["remote-role"], "admin")

    def test_missing_role_uses_default_role(self):
        response = auth(
            self.request(
                {
                    "x-authentik-username": "dominik",
                    "x-proxy-secret": "proxy-secret",
                }
            )
        )
        self.assertEqual(response.headers["remote-role"], "viewer")

    def test_empty_proxy_user_is_hard_failure(self):
        response = auth(
            self.request(
                {
                    **self.jwt_header(),
                    "x-authentik-username": "   ",
                    "x-proxy-secret": "proxy-secret",
                }
            )
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_proxy_secret_is_hard_failure_even_with_jwt(self):
        for supplied_secret in (None, "wrong"):
            headers = {
                **self.jwt_header(),
                "x-authentik-username": "attacker",
            }
            if supplied_secret is not None:
                headers["x-proxy-secret"] = supplied_secret
            with self.subTest(supplied_secret=supplied_secret):
                response = auth(self.request(headers))
                self.assertEqual(response.status_code, 401)

    def test_native_only_preserves_existing_global_proxy_secret_guard(self):
        proxy_config = ProxyConfig(auth_secret="proxy-secret")
        for supplied_secret, expected_status in ((None, 401), ("proxy-secret", 202)):
            headers = self.jwt_header()
            if supplied_secret is not None:
                headers["x-proxy-secret"] = supplied_secret
            with self.subTest(supplied_secret=supplied_secret):
                response = auth(self.request(headers, proxy_config=proxy_config))
                self.assertEqual(response.status_code, expected_status)

    def test_native_only_ignores_proxy_identity_as_authentication_source(self):
        response = auth(
            self.request(
                {"x-authentik-username": "attacker"},
                proxy_config=ProxyConfig(),
            )
        )
        self.assertEqual(response.status_code, 401)

    def test_proxy_only_regression(self):
        response = auth(
            self.request(
                {
                    "x-authentik-username": "dominik",
                    "x-authentik-groups": "frigate-admin",
                    "x-proxy-secret": "proxy-secret",
                },
                auth_config=AuthConfig(enabled=False),
            )
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["remote-user"], "dominik")
        self.assertEqual(response.headers["remote-role"], "admin")

    def test_proxy_logout_redirects_to_upstream(self):
        self.hybrid_proxy.logout_url = "https://auth.example.test/logout"
        response = logout(self.request({"remote-auth-source": "proxy"}))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], self.hybrid_proxy.logout_url)

    def test_native_logout_remains_local(self):
        self.hybrid_proxy.logout_url = "https://auth.example.test/logout"
        response = logout(self.request({"remote-auth-source": "jwt"}))
        self.assertEqual(response.headers["location"], "/login")

    def test_native_logout_preserves_base_path(self):
        response = logout(
            self.request({"remote-auth-source": "jwt", "x-ingress-path": "/frigate"})
        )
        self.assertEqual(response.headers["location"], "/frigate/login")
