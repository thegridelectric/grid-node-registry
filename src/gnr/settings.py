from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
