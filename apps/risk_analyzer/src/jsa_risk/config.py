"""The only module that reads `st.secrets` — everything else asks these functions for
config, so a missing/misconfigured secret surfaces as one friendly message instead of a
raw KeyError reaching the UI."""
from dataclasses import dataclass
from typing import Optional

import streamlit as st

# Defined in the integration module so headless scripts can import it without
# pulling Streamlit in; re-exported here because the app reads config from here.
from jsa_risk.integrations.cme_datamine_client import (  # noqa: F401
    CME_TOKEN_URL,
    CmeDataMineConfig,
    DATAMINE_BASE_URL,
    config_from_dict as cme_datamine_config_from_dict,
)


class ConfigError(RuntimeError):
    """A required secret/config block is missing. Message is safe to show in the UI."""


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    role: str
    warehouse: str
    database: str
    schema: str
    private_key_path: Optional[str] = None
    private_key_pem: Optional[str] = None


@dataclass(frozen=True)
class MassiveConfig:
    api_key: str
    base_url: str


def get_app_password() -> Optional[str]:
    """The shared password the app sits behind, from `[app] password` (or a root-level
    APP_PASSWORD). None when it isn't set -- the gate then refuses everyone rather than
    falling back to a default that would live in the repo."""
    try:
        s = st.secrets
        value = (s["app"].get("password") if "app" in s else None) or (
            s["APP_PASSWORD"] if "APP_PASSWORD" in s else None)
    except Exception:
        return None
    return str(value) if value else None


def _section(name: str, friendly_name: str) -> dict:
    if name not in st.secrets:
        raise ConfigError(
            f"{friendly_name} isn't configured yet — add a [{name}] block to "
            f".streamlit/secrets.toml (see secrets.toml.example)."
        )
    return st.secrets[name]


def _root_snowflake() -> Optional[dict]:
    """The JSA admin portal hosts this app and keeps ONE Snowflake identity as root-level
    secrets (SNOWFLAKE_ACCOUNT / _USER / _ROLE / _WAREHOUSE / _PRIVATE_KEY) instead of a
    [snowflake] block; this reads those, pointed at the app's own JSA.RISK_ANALYZER schema.
    Returns None when they aren't all there (the standalone app, which uses the block)."""
    try:
        s = st.secrets
        if not all(k in s for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY")):
            return None
        return {
            "account": s["SNOWFLAKE_ACCOUNT"], "user": s["SNOWFLAKE_USER"],
            "role": s.get("SNOWFLAKE_ROLE", ""), "warehouse": s.get("SNOWFLAKE_WAREHOUSE", ""),
            "database": "JSA", "schema": "RISK_ANALYZER",
            "private_key_pem": str(s["SNOWFLAKE_PRIVATE_KEY"]).replace("\\n", "\n"),
        }
    except Exception:
        return None


def get_snowflake_config() -> SnowflakeConfig:
    if "snowflake" not in st.secrets:
        root = _root_snowflake()
        if root:
            return SnowflakeConfig(**root)
    s = _section("snowflake", "Snowflake")
    private_key_path = s.get("private_key_path")
    private_key_pem = s.get("private_key_pem")
    if not private_key_path and not private_key_pem:
        raise ConfigError(
            "Snowflake key-pair auth needs either private_key_path (a local file — dev "
            "only) or private_key_pem (the key's contents — required on Streamlit Cloud, "
            "which has no persistent filesystem) in the [snowflake] secrets block."
        )
    return SnowflakeConfig(
        account=s["account"], user=s["user"], role=s["role"], warehouse=s["warehouse"],
        database=s["database"], schema=s["schema"],
        private_key_path=private_key_path, private_key_pem=private_key_pem,
    )


def get_massive_config() -> Optional[MassiveConfig]:
    """Returns None (not an error) when unconfigured — the Massive fetch button just
    disables itself; it's a convenience feature, not a hard dependency."""
    if "massive" not in st.secrets:
        # The admin portal keeps the Massive key at root level (MASSIVE_API_KEY).
        if "MASSIVE_API_KEY" in st.secrets:
            return MassiveConfig(api_key=str(st.secrets["MASSIVE_API_KEY"]), base_url="https://api.massive.com")
        return None
    s = st.secrets["massive"]
    return MassiveConfig(api_key=s["api_key"], base_url=s.get("base_url", "https://api.massive.com"))


def get_cme_datamine_config() -> Optional[CmeDataMineConfig]:
    """Returns None (not an error) when unconfigured — matches get_massive_config's
    convention for an optional integration."""
    if "cme_datamine" not in st.secrets:
        # Root-level form for the admin portal (CME_DATAMINE_API_ID / CME_DATAMINE_PASSWORD).
        if "CME_DATAMINE_API_ID" in st.secrets and "CME_DATAMINE_PASSWORD" in st.secrets:
            return cme_datamine_config_from_dict({"api_id": st.secrets["CME_DATAMINE_API_ID"],
                                                  "password": st.secrets["CME_DATAMINE_PASSWORD"]})
        return None
    return cme_datamine_config_from_dict(st.secrets["cme_datamine"])
