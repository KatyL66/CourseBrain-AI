from openai import AsyncOpenAI

from app.config import settings


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def embed_query(query: str) -> list[float]:
    vectors = await embed_texts([query])
    return vectors[0]
