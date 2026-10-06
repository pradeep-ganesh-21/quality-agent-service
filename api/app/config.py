from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    mongo_uri: SecretStr
    mongo_db_name: str = Field(default="quality_agent", min_length=1)
