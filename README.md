# Copilot Model Provider

`copilot-model-provider` exposes a thin model-provider layer on top of [`github-copilot-sdk`](https://github.com/github/copilot-sdk) so you can point OpenAI-style and Anthropic-style clients at one local service.

Today the main end-user targets are:

- Codex-style clients through `/openai/v1/...`
- Claude-style clients through `/anthropic/v1/...`

## Quick start

### Prerequisites

- Docker
- GitHub CLI (`gh`)
- `uv`
- a logged-in GitHub CLI session: `gh auth login`

The setup scripts restart a local provider container, resolve your `gh auth token`, and rewrite your local client config so future CLI launches use the provider automatically.

### One-line Codex setup from the published image

This command downloads the Codex setup helper and configures Codex to use the latest published GHCR image:

```bash
tmp_dir="$(mktemp -d)" && \
curl -fsSL https://raw.githubusercontent.com/LaChimere/copilot-model-provider/main/scripts/config_codex.py -o "$tmp_dir/config_codex.py" && \
uv run python "$tmp_dir/config_codex.py" --channel release --version latest
```

### One-line Claude setup from the published image

`config_claude.py` reuses shared helper logic from `config_codex.py`, so the bootstrap command downloads both files into one temporary directory before running Claude setup:

```bash
tmp_dir="$(mktemp -d)" && \
curl -fsSL https://raw.githubusercontent.com/LaChimere/copilot-model-provider/main/scripts/config_codex.py -o "$tmp_dir/config_codex.py" && \
curl -fsSL https://raw.githubusercontent.com/LaChimere/copilot-model-provider/main/scripts/config_claude.py -o "$tmp_dir/config_claude.py" && \
uv run python "$tmp_dir/config_claude.py" --channel release --version latest
```

Docker will automatically pull the published image if it is not already present locally.

### Pin to a specific release

If you want a stable pinned version instead of `latest`, replace the version explicitly:

```bash
uv run python scripts/config_codex.py --channel release --version v0.1.0
uv run python scripts/config_claude.py --channel release --version v0.1.0
```

### Use a local development build instead

For local development, build the image yourself and configure against the local tag:

```bash
docker build -t copilot-model-provider:local .
uv run python scripts/config_codex.py --channel local
uv run python scripts/config_claude.py --channel local
```

### Override the image directly

`--image` always wins over `--channel` and `--version`:

```bash
uv run python scripts/config_codex.py --image ghcr.io/lachimere/copilot-model-provider:v0.1.0
uv run python scripts/config_claude.py --image ghcr.io/lachimere/copilot-model-provider:v0.1.0
```

## What the setup scripts do

### `scripts/config_codex.py`

- checks `docker` and `gh`
- ensures `gh` is authenticated
- resolves `gh auth token`
- starts or restarts the provider container
- validates the chosen model against `GET /openai/v1/models`
- backs up `~/.codex/config.toml`
- rewrites Codex config to use the provider

### `scripts/config_claude.py`

- checks `docker`, `gh`, and `claude`
- ensures `gh` is authenticated
- resolves `gh auth token`
- starts or restarts the provider container
- validates the chosen Claude model against `GET /anthropic/v1/models`
- backs up `~/.claude/settings.json`
- rewrites Claude settings so future `claude` launches use the provider

## Current API surface

Available today:

- `GET /openai/v1/models`
- `POST /openai/v1/chat/completions`
- `POST /openai/v1/responses`
- `GET /anthropic/v1/models`
- `POST /anthropic/v1/messages`
- `POST /anthropic/v1/messages/count_tokens`
- `GET /_internal/health`

## How image selection works

The setup scripts support two modes:

- `--channel local`
  - uses `copilot-model-provider:local`
- `--channel release --version <tag>`
  - uses `ghcr.io/lachimere/copilot-model-provider:<tag>`

If you pass `--image`, the script skips channel-based image resolution and uses your explicit image reference.

## Release images

Stable releases are tag-driven.

Maintainer flow:

1. update `pyproject.toml` to the target version
2. merge the release commit to `main`
3. create an annotated tag such as `v0.1.0`
4. push the tag
5. let GitHub Actions publish the GHCR image and create the matching GitHub Release

Example:

```bash
git checkout main
git pull --ff-only
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

On success, the release workflow publishes:

- `ghcr.io/lachimere/copilot-model-provider:v0.1.0`
- `ghcr.io/lachimere/copilot-model-provider:sha-<shortsha>`
- `ghcr.io/lachimere/copilot-model-provider:latest`

## Development

### Requirements

- Python 3.14+
- `uv`

### Install dependencies

```bash
uv sync
```

### Run the service directly

```bash
uv run python -m copilot_model_provider
uv run copilot-model-provider
```

### Run the local container manually

```bash
gh auth login
export GITHUB_TOKEN="$(gh auth token)"
docker build -t copilot-model-provider:local .
docker run --rm \
  -e GITHUB_TOKEN \
  -p 8000:8000 \
  copilot-model-provider:local
```

Auth precedence is:

- request `Authorization: Bearer ...`
- otherwise container `GITHUB_TOKEN` / `GH_TOKEN`

### Lint and type-check

```bash
uv run ruff check .
uv run pyright
uv run ty check .
```

### Run tests

```bash
uv run pytest -q
```

### Opt-in live runtime sweeps

```bash
# Fast mode: verify one preferred visible live model through chat + responses
COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP=1 \
  uv run pytest -q tests/live_tests/test_all_models.py -s

# Full mode: expand the sweep to every currently visible live Copilot model
COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP=1 \
COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP_ALL=1 \
  uv run pytest -q tests/live_tests/test_all_models.py -s
```

## More details

- `docs/design.md` for the architecture and protocol-facade design
- `AGENTS.md` for the repository's agent workflow contract

## License

MIT. See `LICENSE`.
