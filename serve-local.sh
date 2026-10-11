#!/bin/sh
set -eu

cd "$(dirname "$0")"

PYENV_VERSION=3.12.10 python build_site.py
PYENV_VERSION=3.12.10 python -m http.server --bind 127.0.0.1 --directory site 8000
