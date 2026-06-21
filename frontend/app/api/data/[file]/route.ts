import { NextRequest, NextResponse } from "next/server";
import { readFileSync } from "fs";
import { join } from "path";

export const dynamic = "force-dynamic";

const ALLOWED = new Set([
  "hotspots.json",
  "clusters.json",
  "anomalies.json",
  "patrol_routes.json",
  "demo_data.json",
  "commander_context.json",
  "map_roads.json",
  "prediction_export_summary.json",
]);

type RouteContext = { params: Promise<{ file: string }> };

export async function GET(_request: NextRequest, context: RouteContext) {
  const { file } = await context.params;
  if (!ALLOWED.has(file)) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  try {
    const filePath = join(process.cwd(), "public", "fallback", file);
    const data = JSON.parse(readFileSync(filePath, "utf-8"));
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "File not found" }, { status: 404 });
  }
}
