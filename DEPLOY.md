# NammaPark Intel Deploy Notes

## Required Environment Variables

- `DATABASE_URL`: Neon PostgreSQL connection string with PostGIS enabled.
- `UPSTASH_REDIS_URL`: Upstash Redis URL.
- `ANTHROPIC_API_KEY`: Commander LLM key.
- `NEXT_PUBLIC_MAPPLS_KEY`: Mappls browser key.
- `NEXT_PUBLIC_API_BASE_URL`: Deployed FastAPI base URL.
- `SENTRY_DSN`: Optional Sentry project DSN.

## Render API

1. Create a Render web service from this repo.
2. Use `render.yaml`.
3. Set `DATABASE_URL`, `UPSTASH_REDIS_URL`, `ANTHROPIC_API_KEY`, and `SENTRY_DSN`.
4. Deploy.
5. Warm the service with `bash scripts/warmup.sh https://<render-url>/health`.

## Vercel Frontend

The real Next.js frontend is pending task 0.4 / 9.x. After it exists:

1. Import the `frontend/` directory in Vercel when a framework build is added.
2. Set `NEXT_PUBLIC_MAPPLS_KEY` and `NEXT_PUBLIC_API_BASE_URL`.
3. Deploy with the Next.js framework preset.

## Local Demo

The current dependency-free demo remains available:

```bash
npm run generate
npm run dev
```
