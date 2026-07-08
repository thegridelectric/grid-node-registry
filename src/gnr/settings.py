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
    log_level: str = "INFO"
    log_dir: str = "~/.local/state/gridworks/gnr/log"
    db_echo: bool = False

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
