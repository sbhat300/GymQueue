#!/usr/bin/env bash
# Start the vision service. PYTHONPATH is cleared so system (e.g. ROS) packages don't leak into the venv.
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
PYTHONPATH= exec .venv/bin/python -m gymvision.server "$@"
