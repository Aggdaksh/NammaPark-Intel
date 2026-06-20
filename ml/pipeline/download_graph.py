"""Download and persist the Bengaluru OSMnx graph once for offline use."""

from __future__ import annotations

import argparse
from pathlib import Path


ESTIMATE = {
    "operation": "Download Bengaluru OSMnx drive road graph",
    "estimated_final_size": "100-250 MB graphml, plan budget ~200 MB",
    "estimated_temp_size": "300-700 MB Overpass/cache during download",
    "estimated_time": "5-25 minutes depending on Overpass availability",
    "output": "ml/data/bengaluru.graphml",
}


def download_graph(output_path: str | Path = "ml/data/bengaluru.graphml", *, approved: bool = False) -> Path:
    if not approved:
        raise SystemExit(
            "Heavy download not started. Estimate:\n"
            f"- Final size: {ESTIMATE['estimated_final_size']}\n"
            f"- Temp size: {ESTIMATE['estimated_temp_size']}\n"
            f"- Time: {ESTIMATE['estimated_time']}\n"
            "Re-run with --yes after approval."
        )
    try:
        import osmnx as ox  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError("osmnx is required to download the road graph; run `uv sync` first") from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_place("Bengaluru, India", network_type="drive")
    ox.save_graphml(graph, output)
    print({"nodes": len(graph.nodes), "edges": len(graph.edges), "path": str(output)})
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="ml/data/bengaluru.graphml")
    parser.add_argument("--estimate", action="store_true", help="Print estimated size/time and exit")
    parser.add_argument("--yes", action="store_true", help="Confirm the heavy graph download is approved")
    args = parser.parse_args()
    if args.estimate:
        print(ESTIMATE)
        return
    download_graph(args.output, approved=args.yes)


if __name__ == "__main__":
    main()
