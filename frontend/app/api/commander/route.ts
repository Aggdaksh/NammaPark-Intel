import { NextRequest } from "next/server";
import { proxyToBackend } from "../../../lib/proxy";

export const dynamic = "force-dynamic";

export function POST(request: NextRequest) {
  return proxyToBackend(request, ["commander"]);
}
