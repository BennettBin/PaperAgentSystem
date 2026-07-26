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
    ollama_endpoint: str = "http://host.docker.internal:11434"
    embedding_provider: str = "bge_m3"
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_model_version: str = "main"
    embedding_device: str = "auto"
    embedding_batch_size: int = 32
    embedding_max_length: int = 512
    embedding_use_fp16: bool = True
    embedding_query_timeout_ms: int = 300
    embedding_batch_timeout_seconds: float = 30
    embedding_fallback_enabled: bool = True
    embedding_query_cache_ttl_seconds: float = 60
    embedding_query_cache_max_entries: int = 512
    scholarly_api_timeout_seconds: float = 15
    crossref_mailto: str = ""
    semantic_scholar_api_key: str = ""
    openalex_api_key: str = ""
    openalex_mailto: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
