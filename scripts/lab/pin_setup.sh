#!/usr/bin/env bash
# Pin lab dependencies to the versions recorded in the Stage 0 audits.
set -euo pipefail
VIRTUAL_ENV=/opt/all-tomorrow-spike-venv uv pip install -q "restate-sdk[serde]==1.0.5" "fastmcp==4.0.5"
VIRTUAL_ENV=/opt/all-tomorrow-litellm-venv uv pip install -q "litellm[proxy]==1.101.0"
if [ ! -d /opt/all-tomorrow-pydantic-ai-2.45.0 ]; then
  uv pip install -q --python /opt/all-tomorrow-spike-venv/bin/python --target /opt/all-tomorrow-pydantic-ai-2.45.0 --no-deps "pydantic-ai-slim==2.45.0"
fi
/opt/all-tomorrow-spike-venv/bin/python - <<'PY'
import importlib.metadata as m
for p in ("restate-sdk", "fastmcp", "dbos", "pydantic-ai-slim"):
    print(p, m.version(p))
PY
/opt/all-tomorrow-litellm-venv/bin/python -c 'import importlib.metadata as m; print("litellm", m.version("litellm"))'
echo PIN_OK
