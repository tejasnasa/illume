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
        OPENAI_API_KEY (str): API key for OpenAI services.
        AI_MODEL (str): Name of the AI model to use (e.g., gpt-4o-mini).
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
