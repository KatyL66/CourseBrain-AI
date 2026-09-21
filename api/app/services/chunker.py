import re
from dataclasses import dataclass
from html import unescape

import tiktoken

# cl100k_base matches OpenAI text-embedding-3-* and gpt-4o family tokenization
DEFAULT_ENCODING = "cl100k_base"
DEFAULT_CHUNK_SIZE = 700
DEFAULT_OVERLAP = 100


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str


def _get_encoder(encoding_name: str = DEFAULT_ENCODING):
    return tiktoken.get_encoding(encoding_name)


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    encoding_name: str = DEFAULT_ENCODING,
) -> list[TextChunk]:
    """Split text into ordered token-based chunks with overlap."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    encoder = _get_encoder(encoding_name)
    tokens = encoder.encode(text)
    if not tokens:
        return []

    chunks: list[TextChunk] = []
    start = 0
    chunk_index = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        piece = encoder.decode(tokens[start:end]).strip()
        if piece:
            chunks.append(TextChunk(index=chunk_index, text=piece))
            chunk_index += 1
        if end >= len(tokens):
            break
        start += chunk_size - overlap

    return chunks


def strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()
