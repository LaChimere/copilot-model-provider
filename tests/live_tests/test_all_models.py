"""Opt-in live sweeps for one preferred or all visible Copilot models."""

from __future__ import annotations

import os
from typing import cast

import pytest

from copilot_model_provider.config import ProviderSettings
from tests.harness import build_async_client
from tests.runtime_support import list_live_model_ids, resolve_github_token

_RUN_LIVE_SWEEP_ENV = 'COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP'
_RUN_FULL_LIVE_SWEEP_ENV = 'COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP_ALL'
_REQUEST_TIMEOUT_SECONDS = 180.0
_PROMPT = 'Reply with exactly PING and nothing else.'


def _require_live_sweep_opt_in() -> None:
    """Skip the live sweep unless the caller explicitly opts into it.

    The repository keeps the real-auth, all-model sweep out of the default
    pytest path because it depends on external credentials and takes
    substantially longer than the ordinary unit, contract, and container-backed
    integration suites.

    """
    if os.environ.get(_RUN_LIVE_SWEEP_ENV) == '1':
        return

    pytest.skip(
        'Live model sweep is opt-in. Re-run with '
        f'{_RUN_LIVE_SWEEP_ENV}=1 to execute it.'
    )


def _run_full_live_sweep() -> bool:
    """Return whether the caller explicitly requested the all-model sweep.

    Returns:
        ``True`` when the caller opted into the slower full live-model sweep,
        otherwise ``False``.

    """
    return os.environ.get(_RUN_FULL_LIVE_SWEEP_ENV) == '1'


async def _resolve_sweep_targets(*, github_token: str) -> tuple[list[str], str]:
    """Resolve which live model IDs the current sweep should execute.

    Args:
        github_token: Real GitHub bearer token used for runtime execution when
            the caller opted into the full all-model sweep.

    Returns:
        A tuple containing the model IDs to request from the provider and a
        human-readable sweep mode label for diagnostics.

    """
    model_ids = await list_live_model_ids(github_token=github_token)
    if not model_ids:
        return [], 'no-visible-models'

    if not _run_full_live_sweep():
        preferred_model_id = 'gpt-5.4' if 'gpt-5.4' in model_ids else model_ids[0]
        return [preferred_model_id], 'preferred-live-model'

    return (model_ids, 'all-visible-models')


def _extract_completion_text(payload: object) -> str | None:
    """Extract the assistant text from an OpenAI-compatible chat response.

    Args:
        payload: Parsed JSON body returned by the provider route.

    Returns:
        The stripped assistant message content when the payload matches the
        expected response shape, otherwise ``None``.

    """
    if not isinstance(payload, dict):
        return None

    payload_dict = cast('dict[str, object]', payload)
    choices = payload_dict.get('choices')
    if not isinstance(choices, list) or not choices:
        return None

    choices_list = cast('list[object]', choices)
    first_choice = choices_list[0]
    if not isinstance(first_choice, dict):
        return None

    first_choice_dict = cast('dict[str, object]', first_choice)
    message = first_choice_dict.get('message')
    if not isinstance(message, dict):
        return None

    message_dict = cast('dict[str, object]', message)
    content = message_dict.get('content')
    if not isinstance(content, str):
        return None

    return content.strip()


def _extract_responses_output_text(payload: object) -> str | None:
    """Extract assistant text from a minimal OpenAI-compatible Responses payload.

    Args:
        payload: Parsed JSON body returned by the Responses route.

    Returns:
        The stripped assistant output text when the payload matches the expected
        minimal Responses shape, otherwise ``None``.

    """
    if not isinstance(payload, dict):
        return None

    payload_dict = cast('dict[str, object]', payload)
    output = payload_dict.get('output')
    if not isinstance(output, list) or not output:
        return None

    output_list = cast('list[object]', output)
    first_output_item = output_list[0]
    if not isinstance(first_output_item, dict):
        return None

    output_item_dict = cast('dict[str, object]', first_output_item)
    content = output_item_dict.get('content')
    if not isinstance(content, list) or not content:
        return None

    content_list = cast('list[object]', content)
    first_content_item = content_list[0]
    if not isinstance(first_content_item, dict):
        return None

    content_item_dict = cast('dict[str, object]', first_content_item)
    text = content_item_dict.get('text')
    if not isinstance(text, str):
        return None

    return text.strip()


def _parse_json_response_body(response_body: str, content_type: str) -> object:
    """Parse one HTTP response body only when it advertises JSON semantics.

    Args:
        response_body: Raw text body returned by one provider route.
        content_type: Response ``Content-Type`` header value.

    Returns:
        The parsed JSON object when the response declares JSON, otherwise the
        raw text body.

    """
    if content_type.startswith('application/json'):
        import json

        return json.loads(response_body)

    return response_body


async def _run_live_chat_sweep(
    *,
    github_token: str,
    model_ids: list[str],
) -> list[str]:
    """Run the live chat sweep through ``POST /openai/v1/chat/completions``.

    Args:
        github_token: Real GitHub bearer token used for runtime execution.
        model_ids: Provider model IDs requested during the current sweep.

    Returns:
        A list of failure descriptions. An empty list means all models passed.

    """
    settings = ProviderSettings(
        app_name='live-model-sweep',
        environment='test',
        runtime_timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
    )
    failures: list[str] = []

    async with build_async_client(settings=settings) as client:
        for model_id in model_ids:
            response = await client.post(
                '/openai/v1/chat/completions',
                headers={'Authorization': f'Bearer {github_token}'},
                json={
                    'model': model_id,
                    'messages': [{'role': 'user', 'content': _PROMPT}],
                    'stream': False,
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response_body = response.text
            payload = _parse_json_response_body(
                response_body,
                response.headers.get('content-type', ''),
            )
            output_text = _extract_completion_text(payload)

            if response.status_code == 200 and output_text == 'PING':
                continue

            failures.append(
                f'{model_id}: status={response.status_code} output={output_text!r} '
                f'body={payload!r}'
            )

    return failures


async def _run_live_responses_sweep(
    *,
    github_token: str,
    model_ids: list[str],
) -> list[str]:
    """Run the live Responses sweep through ``POST /openai/v1/responses``.

    Args:
        github_token: Real GitHub bearer token used for runtime execution.
        model_ids: Provider model IDs requested during the current sweep.

    Returns:
        A list of failure descriptions. An empty list means all models passed.

    """
    settings = ProviderSettings(
        app_name='live-responses-sweep',
        environment='test',
        runtime_timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
    )
    failures: list[str] = []

    async with build_async_client(settings=settings) as client:
        for model_id in model_ids:
            response = await client.post(
                '/openai/v1/responses',
                headers={'Authorization': f'Bearer {github_token}'},
                json={
                    'model': model_id,
                    'input': _PROMPT,
                    'stream': False,
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response_body = response.text
            payload = _parse_json_response_body(
                response_body,
                response.headers.get('content-type', ''),
            )
            output_text = _extract_responses_output_text(payload)

            if response.status_code == 200 and output_text == 'PING':
                continue

            failures.append(
                f'{model_id}: status={response.status_code} output={output_text!r} '
                f'body={payload!r}'
            )

    return failures


@pytest.mark.asyncio
async def test_live_models_complete_successfully() -> None:
    """Verify that the configured live chat sweep succeeds through the provider.

    By default, the opt-in live sweep exercises one preferred visible live model
    so the check stays fast. When
    ``COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP_ALL=1`` is also set, the test
    expands to every currently visible live Copilot model.

    """
    _require_live_sweep_opt_in()

    github_token = resolve_github_token()
    if github_token is None:
        pytest.skip(
            'Live model sweep requires a real GitHub auth token via '
            'GITHUB_TOKEN/GH_TOKEN or `gh auth token`.'
        )

    model_ids, sweep_mode = await _resolve_sweep_targets(github_token=github_token)
    assert model_ids, 'Expected at least one live Copilot model to be visible.'

    failures = await _run_live_chat_sweep(
        github_token=github_token,
        model_ids=model_ids,
    )
    assert not failures, f'Live chat sweep ({sweep_mode}) failed:\n' + '\n'.join(
        failures
    )


@pytest.mark.asyncio
async def test_live_models_responses_complete_successfully() -> None:
    """Verify that the configured live Responses sweep succeeds through `/openai/v1/responses`.

    This complements the chat-completions live sweep so the provider's two
    implemented northbound execution routes are both covered under the same
    real-auth validation mode. The default opt-in path stays on one preferred
    visible live model, while the explicit all-model mode expands to every
    visible live Copilot model.

    """
    _require_live_sweep_opt_in()

    github_token = resolve_github_token()
    if github_token is None:
        pytest.skip(
            'Live responses sweep requires a real GitHub auth token via '
            'GITHUB_TOKEN/GH_TOKEN or `gh auth token`.'
        )

    model_ids, sweep_mode = await _resolve_sweep_targets(github_token=github_token)
    assert model_ids, 'Expected at least one live Copilot model to be visible.'

    failures = await _run_live_responses_sweep(
        github_token=github_token,
        model_ids=model_ids,
    )
    assert not failures, f'Live responses sweep ({sweep_mode}) failed:\n' + '\n'.join(
        failures
    )
