import { NextRequest, NextResponse } from "next/server";

const BACKEND_BASE =
  process.env.NAMMAPARK_BACKEND_URL ||
  process.env.BACKEND_API_BASE_URL ||
  "http://127.0.0.1:8788";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade"
]);

function backendPathFor(pathSegments: string[]) {
  if (pathSegments.length === 1 && pathSegments[0] === "health") {
    return "/health";
  }
  return `/api/${pathSegments.map(encodeURIComponent).join("/")}`;
}

export async function proxyToBackend(request: NextRequest, pathSegments: string[]) {
  const target = new URL(backendPathFor(pathSegments), BACKEND_BASE);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");

  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.text();

  const backendResponse = await fetch(target, {
    method: request.method,
    headers,
    body,
    redirect: "manual",
    cache: "no-store"
  });

  const responseHeaders = new Headers();
  backendResponse.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: responseHeaders
  });
}
