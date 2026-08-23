#!/bin/bash
# Double-click to browse what has been harvested.
cd "$(dirname "$0")" || exit 1
exec ./.venv/bin/streamlit run harvest/viewer.py
