"""OpenAI text embeddings; API keys are read by the SDK from the environment."""

from openai import OpenAI

from semo.telemetry import no_observation

MODEL = "text-embedding-3-small"


class OpenAIEmbedder:
    def __init__(self, observe=no_observation):
        self.client = OpenAI(timeout=60, max_retries=2)
        self.observe = observe

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
        with self.observe(
            name="semo.embed", as_type="embedding", model=MODEL, input=texts
        ) as embedding:
            response = self.client.embeddings.create(
                model=MODEL, input=texts, encoding_format="float"
            )
            embedding.update(usage_details={"input": response.usage.prompt_tokens})
            ordered = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered] != list(range(len(texts))):
                raise ValueError("OpenAI returned incomplete embedding results")
            return [item.embedding for item in ordered]
