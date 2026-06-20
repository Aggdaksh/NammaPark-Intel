#!/usr/bin/env python3
import json
from pathlib import Path


path = Path("public/fallback/map_roads.json")
payload = json.loads(path.read_text())
segments = payload.get("segments", [])
metadata = payload.get("metadata", {})

assert metadata.get("source") == "ml/data/bengaluru.graphml", metadata
assert len(segments) >= 1000, len(segments)
assert all(len(segment.get("coords", [])) >= 2 for segment in segments[:100])
assert {segment.get("tier") for segment in segments} & {"arterial", "collector", "local"}

print(json.dumps({"status": "ok", "map_roads": len(segments)}, indent=2))
