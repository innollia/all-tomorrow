#!/usr/bin/env bash
# Run the live lab with the given pytest args; print only the summary lines.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export AT_SEMANTIC_TEST_URL=postgresql:///at_semantic_test
timeout "${LAB_TIMEOUT:-1500}" bash scripts/run_00a_live.sh -rs -p no:cacheprovider "$@" > /tmp/lab-last.log 2>&1
grep -E "passed|failed|^FAILED|^ERROR|^E  |^SKIPPED|lab evidence" /tmp/lab-last.log | tail -40
