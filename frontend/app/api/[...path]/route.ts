import { NextRequest } from "next/server";
import { proxyToBackend } from "../../../lib/proxy";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

async function pathSegments(context: RouteContext) {
  const params = await context.params;
  return params.path;
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, await pathSegments(context));
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, await pathSegments(context));
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, await pathSegments(context));
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, await pathSegments(context));
}

export async function OPTIONS(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, await pathSegments(context));
}
