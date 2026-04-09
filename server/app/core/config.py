from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    REDIS_URL: str
    OPENAI_API_KEY: str
    AI_MODEL: str

    class Config:
        env_file = ".env"


settings = Settings() #type: ignore
