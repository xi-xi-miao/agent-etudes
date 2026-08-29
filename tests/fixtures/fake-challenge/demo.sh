#!/usr/bin/env bash
# Round-trip demo for the fixture challenge. Deliberately a no-op: the shared
# tests only need `demo.sh` to exist, be executable and exit 0.
set -euo pipefail
echo "fake-challenge demo: generate -> baseline -> validate -> render (no-op)"
