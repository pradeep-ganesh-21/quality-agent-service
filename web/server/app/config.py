from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    api_base_url: str = "http://api:8000"
    httpx_connect_timeout_seconds: float = 5
    httpx_read_timeout_seconds: float = 30
    httpx_write_timeout_seconds: float = 30
    httpx_pool_timeout_seconds: float = 5
