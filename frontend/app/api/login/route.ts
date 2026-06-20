import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { username, password } = body;

    // Simple hardcoded authentication for the demo
    if (username === "operator" && password === "gridlock") {
      return NextResponse.json({ success: true, message: "Logged in successfully" });
    }

    return NextResponse.json(
      { error: "Invalid credentials" },
      { status: 401 }
    );
  } catch (e) {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
}
