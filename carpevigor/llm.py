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
from typing import Callable, Type, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

mock_answers: dict[str, Callable[[str], BaseModel]] = {}


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


def _vertex(system: str, task: str, shape: Type[T], model: str, temperature: float) -> T:
    global _vertex_client
    from google import genai  # imported here so mock mode needs no SDK
    from google.genai import types

    if _vertex_client is None:
        _vertex_client = genai.Client(vertexai=True, project=config.GOOGLE_CLOUD_PROJECT, location=config.GOOGLE_CLOUD_LOCATION)
    response = _vertex_client.models.generate_content(
        model=model, contents=task,
        config=types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                           response_mime_type="application/json", response_schema=shape))
    parsed = response.parsed
    return parsed if isinstance(parsed, shape) else shape.model_validate_json(response.text)


def _bedrock(system: str, task: str, shape: Type[T], model: str, temperature: float) -> T:
    import boto3
    from strands import Agent
    from strands.models import BedrockModel

    bedrock = BedrockModel(model_id=model, boto_session=boto3.Session(region_name=config.AWS_REGION), temperature=temperature)
    agent = Agent(model=bedrock, system_prompt=system, callback_handler=None)
    return agent(task, structured_output_model=shape).structured_output
