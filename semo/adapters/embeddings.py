"""OpenAI text embeddings; API keys are read by the SDK from the environment."""

from openai import OpenAI

MODEL = "text-embedding-3-small"


class OpenAIEmbedder:
    def __init__(self):
        self.client = OpenAI(timeout=60, max_retries=2)

    def __call__(self, texts: list[str]) -> list[list[float]]:
        # A byte is an upper bound on BPE token count; keep requests below model/API limits.
        if (
            not texts
            or len(texts) > 32
            or any(
                not text.strip() or len(text.encode("utf-8")) > 8000 for text in texts
            )
        ):
            raise ValueError(
                "Embedding inputs must contain 1–32 nonempty strings of at most 8000 UTF-8 bytes"
            )
        response = self.client.embeddings.create(
            model=MODEL, input=texts, encoding_format="float"
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(texts))):
            raise ValueError("OpenAI returned incomplete embedding results")
        return [item.embedding for item in ordered]
