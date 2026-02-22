import { NextRequest } from "next/server";

const BACKEND = "http://127.0.0.1:8050";

export async function POST(req: NextRequest) {
  const date = req.nextUrl.searchParams.get("date") || "";

  const upstream = await fetch(
    `${BACKEND}/api/signals/generate-stream?date=${date}`,
    { method: "POST" }
  );

  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), { status: upstream.status });
  }

  // Pipe the upstream SSE body straight through with no buffering
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
