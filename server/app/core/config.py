from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
