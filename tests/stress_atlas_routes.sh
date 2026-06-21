#!/bin/sh
set -eu

BASE_URL="${1:-http://127.0.0.1:8765}"
PROJECT_ID="${2:-1d37d579ab96}"

echo "Stress testing Atlas GUI routes against ${BASE_URL} for project ${PROJECT_ID}"

check_route() {
  route="$1"
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE_URL}/projects/${PROJECT_ID}${route}")"
  if [ "$code" != "303" ]; then
    echo "Route ${route} returned ${code}, expected 303" >&2
    exit 1
  fi
  echo "OK ${route} -> ${code}"
}

for _i in 1 2 3; do
  check_route "/prepare_handoff"
  check_route "/atlas/run_research"
  check_route "/atlas/open_home"
  check_route "/atlas/attempt_deep_research"
  check_route "/atlas/copy_research"
  check_route "/atlas/stage_research"
done

HANDOFF_DIR="$HOME/.paperorchestra/gui/workspaces/gui-smoke-paper/chatgpt_handoff"
test -f "${HANDOFF_DIR}/README.md"
test -f "${HANDOFF_DIR}/02_deep_research_literature.md"
test -f "${HANDOFF_DIR}/policy.json"

echo "Atlas route stress test completed successfully."
