#!/bin/sh
# The whole record — everyone's. Yours only: it reads the secret key, which
# bypasses every row-level policy. Never hand this file or its output out.
cd "$(dirname "$0")" || exit 1
./.venv/bin/python -m harvest admin || exit 1
open out/admin.html
