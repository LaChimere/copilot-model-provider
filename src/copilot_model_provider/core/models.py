"""Canonical internal data models for the provider scaffold."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionMode = Literal['stateless', 'sessional']


class RuntimeHealth(BaseModel):
    """Health metadata for a runtime backend."""

    model_config = ConfigDict(frozen=True)

    runtime: str = Field(min_length=1)
    available: bool
    detail: str | None = None


class InternalHealthResponse(BaseModel):
    """Response shape for the internal-only health endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal['ok'] = 'ok'
    service: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    runtime: RuntimeHealth


class CanonicalRequest(BaseModel):
    """Minimal normalized request contract for later provider phases."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    conversation_id: str | None = None
    model_alias: str | None = None
    execution_mode: ExecutionMode = 'stateless'


class ModelCatalogEntry(BaseModel):
    """Service-owned catalog entry used for public model listing and routing."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    owned_by: str = Field(min_length=1)
    runtime_model_id: str = Field(min_length=1)
    created: int = Field(ge=0, default=0)
    session_mode: ExecutionMode = 'stateless'


class OpenAIModelCard(BaseModel):
    """OpenAI-compatible model card returned from ``GET /v1/models``."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    object: Literal['model'] = 'model'
    created: int = Field(ge=0, default=0)
    owned_by: str = Field(min_length=1)


class OpenAIModelListResponse(BaseModel):
    """OpenAI-compatible response body for the model catalog endpoint."""

    model_config = ConfigDict(frozen=True)

    object: Literal['list'] = 'list'
    data: list[OpenAIModelCard]


class ResolvedRoute(BaseModel):
    """Minimal route resolution contract for runtime selection."""

    model_config = ConfigDict(frozen=True)

    runtime: str = Field(min_length=1)
    session_mode: ExecutionMode = 'stateless'
    runtime_model_id: str | None = None
