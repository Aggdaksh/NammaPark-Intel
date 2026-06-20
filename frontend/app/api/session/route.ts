import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    authenticated: true,
    user: "operator",
    expires_at: Date.now() + 86400000,
  });
}
