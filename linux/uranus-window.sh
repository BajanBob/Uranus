#!/usr/bin/env bash
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then exec .venv/bin/python uranus_app.py; else exec python3 uranus_app.py; fi
