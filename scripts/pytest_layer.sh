#!/usr/bin/env bash
# CI test-layer runner (LM-ARCH-001 §21.4 pipeline).
#
# Runs pytest over the given test directories. During the M0 staging the
# pipeline stages appear before their content (§22.1 scope fence), so:
#   - a missing directory  -> transparent skip with a notice
#   - pytest rc=5 ("no tests collected") -> transparent skip with a notice
#   - any other failure    -> fails the pipeline
#
# Interpreter resolution: prefer agent/.venv when present so that a repo-root
# invocation (the CI style) cannot accidentally resolve a PATH pytest that
# lacks the Agent's pinned deps (sandbox global venvs shadow PATH). In CI the
# venv does not exist and PATH pytest is used exactly as before.
set -u

PYTEST=pytest
if [ -x "agent/.venv/bin/pytest" ]; then
  PYTEST="agent/.venv/bin/pytest"
fi

rc=0
found_any=0
collected_any=0

for d in "$@"; do
  if [ ! -d "$d" ]; then
    continue
  fi
  found_any=1
  rc=0
  "$PYTEST" "$d" -v || rc=$?
  if [ "$rc" -eq 0 ]; then
    collected_any=1
  elif [ "$rc" -eq 5 ]; then
    echo "::notice::pytest collected no tests in '$d' yet (layer content lands with a later WP, §22.1)"
  else
    exit "$rc"
  fi
done

if [ "$found_any" -eq 0 ]; then
  echo "::notice::no test directories present yet for: $* (M0 staging per §22.1)"
elif [ "$rc" -eq 5 ] || [ "$collected_any" -eq 0 ]; then
  echo "::notice::no tests executed for: $*"
fi
exit 0
