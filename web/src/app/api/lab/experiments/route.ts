import { NextRequest } from "next/server";

const BACKEND = "http://127.0.0.1:8050";

// Proxy GET through to backend (route handlers override rewrites)
export async function GET(req: NextRequest) {
  const qs = req.nextUrl.search;
  const upstream = await fetch(`${BACKEND}/api/lab/experiments${qs}`);
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function POST(req: NextRequest) {
  const body = await req.text();

  const upstream = await fetch(`${BACKEND}/api/lab/experiments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
