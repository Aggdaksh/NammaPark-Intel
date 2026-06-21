import { NextResponse } from "next/server";
import { readFileSync } from "fs";
import { join } from "path";

export const dynamic = "force-dynamic";

function readFallback(filename: string) {
  try {
    return JSON.parse(readFileSync(join(process.cwd(), "public", "fallback", filename), "utf-8"));
  } catch {
    return null;
  }
}

export async function GET() {
  const data = readFallback("patrol_routes.json");
  if (!data) return NextResponse.json({ metadata: {}, items: [] });
  return NextResponse.json(data);
}
