"""
Application configuration and environment variable management.

Loads settings from environment variables and `.env` files using Pydantic.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Global application settings schema.
    
    Attributes:
        DATABASE_URL (str): Async PostgreSQL connection string.
        SYNC_DATABASE_URL (str): Synchronous PostgreSQL connection string.
        REDIS_URL (str): Redis connection string.
        OPENAI_API_KEY (str): API key for OpenAI services. Used for embeddings only
            after the BYOK split; all generation moves to either the user’s stored key
            or the server’s DeepSeek key (``AI_API_KEY``).
        AI_MODEL (str): Name of the AI model to use for the **free-tier** generation
            path. Becomes free-tier-only after the BYOK split -- the four generation
            services no longer read it directly, instead receiving an ``LLMConfig``
            that resolves model/base URL from either the user’s row or the registry
            defaults. Empty means the DeepSeek registry default.
        AI_API_KEY (str): The operator’s DeepSeek key, used when a user has no key
            of their own (the free tier). Empty disables the free tier entirely
            rather than crashing -- a missing key surfaces as ``LLMConfig.server_default()``
            returning ``None`` and the route layer returning 402.
        AI_BASE_URL (str): Override for the free tier’s base URL. Empty means the
            DeepSeek registry default (``https://api.deepseek.com``, **without** ``/v1``).
        ACCESS_TOKEN_EXPIRE_MINUTES (int): JWT token validity duration.
        SECRET_KEY (str): Secret key for JWT signing.
        FRONTEND_URL (str): CORS allowed origin for the frontend.
        ENVIRONMENT (str): Deployment environment (e.g., development, production).
        GITHUB_CLIENT_ID (str): GitHub OAuth client ID.
        GITHUB_CLIENT_SECRET (str): GitHub OAuth client secret.
        GITHUB_REDIRECT_URL (str): GitHub OAuth redirect URI.
    """
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    REDIS_URL: str
    OPENAI_API_KEY: str
    AI_MODEL: str
    AI_API_KEY: str = ""
    AI_BASE_URL: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SECRET_KEY: str
    FRONTEND_URL: str
    ENVIRONMENT: str = "development"
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    GITHUB_REDIRECT_URL: str
    DOMAIN: str

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()  # type: ignore
