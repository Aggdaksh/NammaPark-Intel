import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    user: {
      username: "operator",
      role: "admin",
    },
    expires: new Date(Date.now() + 86400000).toISOString(),
  });
}
