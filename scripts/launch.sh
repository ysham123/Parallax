#!/bin/sh
set -eu
PARALLAX_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$PARALLAX_ROOT/scripts/parallax.py" "$@"
