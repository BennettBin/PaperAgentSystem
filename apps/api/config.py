from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_workers: int = 1
    secret_key: str | None = None
    allowed_hosts: str = "localhost,127.0.0.1"
    model_router_endpoint: str | None = None
    adapter_mode: Literal["fake", "real"] = "fake"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_environment_requirements(self) -> "ApiSettings":
        if self.environment == "production":
            missing = [
                name
                for name, value in {
                    "SECRET_KEY": self.secret_key,
                    "MODEL_ROUTER_ENDPOINT": self.model_router_endpoint,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError("Missing required production configuration: " + ", ".join(missing))
        return self
