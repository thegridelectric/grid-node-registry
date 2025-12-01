from typing import Optional
from pydantic import ConfigDict, SecretStr
from pydantic_settings import BaseSettings

DEFAULT_ENV_FILE = ".env"

class Settings(BaseSettings):
    db_url: SecretStr = SecretStr(
        "postgresql+psycopg://gnr:gnrpass@localhost:5432/gnr"
    )
    log_level: str = "INFO"
    log_dir: str = "~/.local/state/gridworks/gnr/log"
    db_echo: bool = False

    model_config = ConfigDict(
        env_prefix="gnr_",
        env_nested_delimiter="__",
        extra="ignore",
    )