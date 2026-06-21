from pydantic_settings import BaseSettings, SettingsConfigDict


class InfrastructureSettings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://paperagent:dev_password_change_in_production"
        "@localhost:5432/paperagent"
    )
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket_prefix: str = "paperagent"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
