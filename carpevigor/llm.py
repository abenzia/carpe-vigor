"""One door to the language models: `ask(system, task, shape, tier)` returns an instance of `shape` (a pydantic model).

Providers:
- `vertex`  — Gemini on Google Vertex AI through the `google-genai` SDK, structured output from the pydantic
              schema. Needs GOOGLE_CLOUD_PROJECT (+ location) and `gcloud auth application-default login`.
- `bedrock` — Amazon Nova through Strands Agents, as the engine ran in Carpe Class. Needs an AWS profile.
- `mock`    — no network, deterministic answers the tests and the credential-less demo rely on; each module
              registers what the mock answers for its own shape (`mock_answers`). The mock never pretends to
              review: a mock juror marks every statement "supported" and the UI says the board was simulated.

`tier` is strong | mid | light: the fact jurors use one tier each, so they are three different models.
"""
from __future__ import annotations

import os
import re
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Type, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

mock_answers: dict[str, Callable[[str], BaseModel]] = {}
RETRY_WAITS = (3.0, 8.0, 20.0, 45.0)  # seconds before each new try of a call Vertex refused with 429: the quota is per minute


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", config.LLM_PROVIDER)


def model_for(tier: str) -> str:
    return config.MODELS[provider()][tier]


def ask(system: str, task: str, shape: Type[T], tier: str = "strong", temperature: float = 0.1) -> T:
    p = provider()
    if p == "vertex":
        return _vertex(system, task, shape, model_for(tier), temperature)
    if p == "bedrock":
        return _bedrock(system, task, shape, model_for(tier), temperature)
    maker = mock_answers.get(shape.__name__)
    if not maker:
        raise RuntimeError(f"mock provider has no answer registered for {shape.__name__}")
    answer = maker(task)
    return answer if isinstance(answer, shape) else shape.model_validate(answer)


_vertex_client = None


_client_lock = threading.Lock()


def _client():
    """One client for the process. The lock matters: parallel calls (the board, the embeddings) used to create one
    client each; the extra ones were garbage-collected and closed while their requests were still running."""
    global _vertex_client
    with _client_lock:
        if _vertex_client is None:
            from google import genai  # imported here so mock mode needs no SDK
            _vertex_client = genai.Client(vertexai=True, project=config.GOOGLE_CLOUD_PROJECT, location=config.GOOGLE_CLOUD_LOCATION)
        return _vertex_client


def embed(texts: list[str], task: str) -> list[list[float]]:
    """One vector per text. `task`: RETRIEVAL_DOCUMENT for the source passages, RETRIEVAL_QUERY for the claims.
    Vertex: ONE text per call — gemini-embedding-2 reads a list of texts as one content and returns one vector,
    without an error. Mock: a bag of words hashed into 256 numbers, enough for the tests to retrieve by keyword."""
    if provider() != "vertex":
        return [_mock_vector(t) for t in texts]
    from google.genai import types
    settings = types.EmbedContentConfig(task_type=task, output_dimensionality=config.EMBED_DIMENSIONS)

    def one(text: str) -> list[float]:
        vectors = _client().models.embed_content(model=config.EMBED_MODEL, contents=text, config=settings).embeddings
        if len(vectors) != 1:
            raise RuntimeError(f"{config.EMBED_MODEL} returned {len(vectors)} vectors for one text")
        return list(vectors[0].values)
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, texts))


def _mock_vector(text: str) -> list[float]:
    vector = [0.0] * 256
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if len(word) > 2:
            vector[zlib.crc32(word.encode()) % 256] += 1.0
    return vector


def _vertex(system: str, task: str, shape: Type[T], model: str, temperature: float) -> T:
    from google.genai import types

    settings = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                           response_mime_type="application/json", response_schema=shape)
    for wait in RETRY_WAITS + (None,):
        try:
            response = _client().models.generate_content(model=model, contents=task, config=settings)
            break
        except Exception as error:
            # 429: the board sends several calls to the same model at once and Vertex sometimes says "try again later".
            # Only that is retried; anything else, or a 429 after the last wait, goes up to the caller as it is.
            if wait is None or getattr(error, "code", None) != 429:
                raise
            time.sleep(wait)
    parsed = response.parsed
    return parsed if isinstance(parsed, shape) else shape.model_validate_json(response.text)


def _bedrock(system: str, task: str, shape: Type[T], model: str, temperature: float) -> T:
    import boto3
    from strands import Agent
    from strands.models import BedrockModel

    bedrock = BedrockModel(model_id=model, boto_session=boto3.Session(region_name=config.AWS_REGION), temperature=temperature)
    agent = Agent(model=bedrock, system_prompt=system, callback_handler=None)
    return agent(task, structured_output_model=shape).structured_output
