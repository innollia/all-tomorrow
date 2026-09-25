#!/usr/bin/env bash
# Disposable Ubuntu/WSL live 00A lab. PostgreSQL test databases must already exist.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

spike_python="${AT_SPIKE_PYTHON:-/opt/all-tomorrow-spike-venv/bin/python}"
litellm_bin="${AT_LITELLM_BIN:-/opt/all-tomorrow-litellm-venv/bin/litellm}"
restate_bin="${AT_RESTATE_BIN:-/opt/restate/1.7.10/restate-server-x86_64-unknown-linux-musl/restate-server}"
lab_dir="$(mktemp -d /tmp/all-tomorrow-00a-live.XXXXXX)"
artifact_root="${AT_LIVE_ARTIFACT_DIR:-$repo_dir/.artifacts/00a}"
mkdir -p "$artifact_root"
artifact_dir="$(mktemp -d "$artifact_root/run.XXXXXX")"
exec > >(tee "$artifact_dir/console.log") 2>&1
cat /proc/sys/kernel/random/boot_id > "$artifact_dir/boot-id.txt"
pids=()

cleanup() {
  local pid
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  sleep 2
  for pid in "${pids[@]}"; do
    kill -KILL "$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  echo "00A lab evidence: $artifact_dir; temporary state: $lab_dir" >&2
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local i
  for i in $(seq 1 160); do
    if curl --fail --silent --max-time 1 --output /dev/null "$url"; then
      return 0
    fi
    sleep 0.25
  done
  echo "Service unavailable: $url" >&2
  return 1
}

wait_port() {
  local port="$1"
  local i
  for i in $(seq 1 160); do
    if (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      return 0
    fi
    sleep 0.25
  done
  echo "Port unavailable: $port" >&2
  return 1
}

pg_isready -q
psql at_dbos_probe -Atc 'SELECT 1' >/dev/null
psql at_external_fixture -Atc 'SELECT 1' >/dev/null
export AT_TEST_POSTGRES_URL=postgresql:///at_dbos_probe
export AT_TEST_FIXTURE_URL=postgresql:///at_external_fixture
for port in 9070 8080 9080 9191 9192 9193 4000; do
  if (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "Port $port is already in use; stop the existing lab first" >&2
    exit 1
  fi
done

"$restate_bin" --base-dir "$lab_dir/restate" --no-logo >"$artifact_dir/restate.log" 2>&1 &
pids+=("$!")
wait_http http://127.0.0.1:9070/health
kill -0 "${pids[0]}"

"$spike_python" -m uvicorn tests.support.restate_probe_service:app --host 127.0.0.1 --port 9080 >"$artifact_dir/probe.log" 2>&1 &
pids+=("$!")
wait_http http://127.0.0.1:9080/health
curl --fail --silent --show-error --max-time 10 \
  -H 'Content-Type: application/json' \
  -d '{"uri":"http://127.0.0.1:9080","use_http_11":true}' \
  http://127.0.0.1:9070/deployments >"$lab_dir/probe-registration.json"

for entry in alpha:9191 beta:9192 gamma:9193; do
  name="${entry%%:*}"
  port="${entry##*:}"
  "$spike_python" -m tests.support.mcp_upstream "$name" "$port" >"$artifact_dir/$name.log" 2>&1 &
  pids+=("$!")
  wait_port "$port"
done

"$litellm_bin" --config tests/support/litellm_mcp_probe_added.yaml --port 4000 >"$artifact_dir/litellm.log" 2>&1 &
pids+=("$!")
wait_port 4000

export AT_TEST_RESTATE_ADMIN=http://127.0.0.1:9070
export AT_TEST_RESTATE_INGRESS=http://127.0.0.1:8080
export AT_TEST_LITELLM_MCP_URL=http://127.0.0.1:4000/mcp
export AT_TEST_GATEWAY_EXPECT_GAMMA=1
export AT_TEST_LITELLM_BIN="$litellm_bin"

"$spike_python" -m pytest -q --junitxml="$artifact_dir/results.xml" "$@"
