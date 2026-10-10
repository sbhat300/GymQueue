"""Print GymQueue machine ids, to use as machine_id in cameras.json.

    PYTHONPATH= .venv/bin/python scripts/list_machines.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gymvision.backend import machines  # noqa: E402

for m in machines():
    print(f"{m['campus']:<30} {m['name']:<20} {m['id']}")
print("\nexample cameras.json entry:")
m = machines()[0]
print(json.dumps([{"machine_id": m["id"], "name": m["name"], "source": "webcam:0"}]))
