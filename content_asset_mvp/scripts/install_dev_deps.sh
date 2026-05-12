#!/usr/bin/env bash
set -euo pipefail
~/venv-content-mvp/bin/pip install --quiet "$@"
~/venv-content-mvp/bin/python -c "from PIL import Image, ImageFilter, ImageStat; print('Pillow OK')"
