import type { SectionConfigOverrides } from "./types";

const auth: SectionConfigOverrides = {
  base: {
    sectionDocs: "/configuration/authentication",
    restartRequired: [
      "enabled",
      "reset_admin_password",
      "failed_login_rate_limit",
    ],
    fieldOrder: [
      "enabled",
      "reset_admin_password",
      "cookie_name",
      "cookie_secure",
      "session_length",
      "refresh_time",
      "oidc",
      "failed_login_rate_limit",
      "trusted_proxies",
      "hash_iterations",
      "roles",
    ],
    hiddenFields: ["admin_first_time_login", "roles"],
    advancedFields: [
      "cookie_name",
      "cookie_secure",
      "session_length",
      "refresh_time",
      "oidc",
      "failed_login_rate_limit",
      "trusted_proxies",
      "hash_iterations",
      "roles",
    ],
    uiSchema: {
      reset_admin_password: {
        "ui:widget": "switch",
      },
      oidc: {
        enabled: {
          "ui:widget": "switch",
        },
        client_secret: {
          "ui:widget": "password",
        },
      },
      failed_login_rate_limit: {
        "ui:options": { size: "md" },
      },
    },
  },
};

export default auth;
