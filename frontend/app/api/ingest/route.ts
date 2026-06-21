import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const FASTAPI_BASE =
  process.env.NAMMAPARK_FASTAPI_URL ||
  process.env.FASTAPI_API_BASE_URL ||
  "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const target = new URL("/api/ingest", FASTAPI_BASE);

  try {
    const response = await fetch(target, {
      method: "POST",
      body: formData,
      cache: "no-store"
    });
    const text = await response.text();
    return new NextResponse(text, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json; charset=utf-8"
      }
    });
  } catch {
    return NextResponse.json(
      {
        status: "unavailable",
        detail:
          "FastAPI ingestion service is not reachable. Start `npm run api` or set NAMMAPARK_FASTAPI_URL before uploading CSV files."
      },
      { status: 503 }
    );
  }
}
