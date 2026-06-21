import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    status: "ok",
    model: true,
    model_version: "v1-osm",
    db: false,
    cache: "fallback",
    cache_tier: "fallback",
  });
}
