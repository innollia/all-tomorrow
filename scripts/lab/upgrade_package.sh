#!/usr/bin/env bash
# Re-lock one package and reinstall the repo into the lab venv (dependency-update rail).
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo"
uv lock --upgrade-package "$1" 2>&1 | tail -3
VIRTUAL_ENV=/opt/all-tomorrow-spike-venv uv pip install -q "$repo" "restate-sdk[serde]==1.0.5" "fastmcp==4.0.5"
rm -rf "$repo/build"
/opt/all-tomorrow-spike-venv/bin/python -c "import importlib.metadata as m, sys; print(sys.argv[1], m.version(sys.argv[1]))" "$1"
