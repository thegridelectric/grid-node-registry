from gwbase import ServiceSettings
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The single production universe's requirements that are still stubs. Booting a
# `w…` registry refuses until every one of these is implemented and removed from
# this list — production cannot be stood up prematurely or by accident.
PROD_STUBS = (
    "Proof verification on write commands",
    "the validation-cert (TaValidator/TaDeed) plane",
    "encrypted position_points",
)


class Settings(BaseSettings):
    # The universe this registry instance serves (e.g. `d1`, `hw1`). REQUIRED,
    # no default: a registry is scoped to exactly one universe (executor
    # *Universes*) and the deployer must declare it. Every alias the registry
    # holds or accepts must carry this as its first dotted segment.
    universe: str
    db_url: SecretStr = SecretStr(
        "postgresql+psycopg://gnr:gnrpass@localhost:5435/gnr"
    )
    db_echo: bool = False
    # Stop-gap write authorization until mTLS+FIS: when set, every write
    # command (create / re-parent) must carry a Proof whose sha256 hex equals
    # this value. The secret itself lives only with the operator; the deploy
    # holds the hash. Unset = gate off (dev harness).
    write_proof_sha256: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="gnr_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @field_validator("universe")
    @classmethod
    def _check_universe(cls, v: str) -> str:
        if not (v.isalnum() and v.islower() and v[0].isalpha()):
            raise ValueError(
                f"universe {v!r} must be a single lowercase alphanumeric word "
                "(the first dotted segment of every alias in this registry)"
            )
        if v[0] not in "dhw":
            raise ValueError(
                f"universe {v!r} must start with its kind letter: d (dev), "
                "h (hybrid), or w (production)"
            )
        if v[0] == "w":
            raise ValueError(
                "a production-universe registry cannot boot yet — still stubs: "
                + "; ".join(PROD_STUBS)
                + ". See wiki/grid-node-registry (populate-and-deploy spoke)."
            )
        return v


class RabbitRunSettings(ServiceSettings):
    """Deploy config for `gnr rabbit`, all in the single `.env` under the one
    `GNR_` prefix: broker connection + service identity (the inherited
    `ServiceSettings` fields, e.g. `GNR_RABBIT__URL`, `GNR_SERVICE_ALIAS`)
    plus which supervisor and time coordinator this registry answers to —
    REQUIRED, no defaults: orchestration wiring is the deployer's
    declaration."""

    super_alias: str
    time_coordinator_alias: str
    # XDG path segment: the actor logs to ~/.local/state/gridworks/gnr/log/
    # (gwbase paths convention; inherited default would say "gridworks").
    service_name: str = "gnr"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="gnr_",
        env_nested_delimiter="__",
        extra="ignore",
    )


class ApiRunSettings(BaseSettings):
    """Bind config for `gnr api`. Loopback by default — the TLS proxy (Caddy)
    fronts it in deploy; a non-local bind is a deliberate declaration."""

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="gnr_",
        env_nested_delimiter="__",
        extra="ignore",
    )
