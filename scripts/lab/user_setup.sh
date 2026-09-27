#!/usr/bin/env bash
# User-level venvs for the all-tomorrow live lab (WSL Ubuntu). Idempotent.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ ! -x /opt/all-tomorrow-spike-venv/bin/python ]; then
  uv venv -q --python 3.13 /opt/all-tomorrow-spike-venv
fi
VIRTUAL_ENV=/opt/all-tomorrow-spike-venv uv pip install -q "$repo" "restate-sdk[serde]" fastmcp openai "pytest>=8.3,<9" "pytest-asyncio>=0.24,<1"
if [ ! -x /opt/all-tomorrow-litellm-venv/bin/litellm ]; then
  uv venv -q --python 3.13 /opt/all-tomorrow-litellm-venv
  VIRTUAL_ENV=/opt/all-tomorrow-litellm-venv uv pip install -q "litellm[proxy]"
fi
/opt/all-tomorrow-spike-venv/bin/python -c "import restate, dbos, fastmcp; print('spike ok', dbos.__version__ if hasattr(dbos,'__version__') else '')"
/opt/all-tomorrow-litellm-venv/bin/litellm --version 2>&1 | tail -1
echo USER_SETUP_OK
