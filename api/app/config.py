from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    data_dir: str = "data"
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    embedding_dimensions: int = 1536
    debug_mode: bool = False
    coursebrain_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
