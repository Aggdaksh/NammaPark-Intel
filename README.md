# NammaPark Intel Local Demo

NammaPark Intel turns the provided Bengaluru parking-violation CSV into a runnable enforcement-intelligence demo: priority-zone rankings, BPR-style delay, exception alerts, patrol assignments, cluster explanations, and a command-assistant endpoint grounded in the generated cluster context.

This implementation is intentionally local-first for the hackathon. It mirrors the plan's fallback tier by precomputing JSON artifacts in `public/fallback`, then serving them through the planned API routes. The cloud pieces from the expert plan, such as Neon, Upstash, FastAPI, Claude, LightGBM, H3, and OR-Tools, are represented by clean local equivalents so the demo runs without network access or secrets.

## Run

```bash
npm run generate
npm run dev
```

Open `http://localhost:8787`.

## Verify

```bash
npm test
```

## Structure

- `frontend/`: login, dashboard, map, and Command Assistant browser pages.
- `backend/node/`: local demo server used by `npm run dev`.
- `api/`: FastAPI package for the production API contract.
- `ml/`: ML training, prediction, evaluation, schema, and model artifacts.
- `public/fallback/`: precomputed JSON served by the local demo and FastAPI fallback layer.

See `docs/ARCHITECTURE.md` for the full module map.

## Latest Notes

See `docs/CHANGES_NOTE.md` for a concise record of the site polish, ML-stack guarantee, and remaining production-build work.

## API

- `GET /health`
- `GET /api/hotspots`
- `GET /api/cluster/:cluster_id`
- `GET /api/patrol-routes`
- `GET /api/anomalies`
- `POST /api/commander` with `{ "user_message": "Why is cluster 12 risky?" }`

## What Is Implemented

- CSV parsing and validation against Bengaluru coordinate bounds.
- BPR-style delay estimates using road-capacity heuristics from location, junction, vehicle, and violation context.
- Stable grid-based spatial clusters with H3-compatible response fields.
- Cluster risk ranking normalised to `final_risk_0_100`.
- SHAP-style top-driver explanations derived from the same aggregate features that produce the score.
- Anomaly flags from hour-of-day z-scores.
- Greedy multi-unit patrol routing with Haversine travel time and delay-cleared estimates.
- Dependency-free local API server and dashboard.

## Generated Files

`npm run generate` writes:

- `public/fallback/demo_data.json`
- `public/fallback/hotspots.json`
- `public/fallback/clusters.json`
- `public/fallback/patrol_routes.json`
- `public/fallback/anomalies.json`
- `public/fallback/commander_context.json`
- `public/fallback/etl_report.json`

These files are safe to regenerate from the raw CSV.
