import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import { startClaudeJob, getOrCreateSession } from "@/lib/claude-worker";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const message = body.message as string | undefined;
  const sessionId = (body.session_id as string) || randomUUID();

  if (!message?.trim()) {
    return NextResponse.json(
      { error: "message is required" },
      { status: 400 },
    );
  }

  const messageId = randomUUID();

  // Ensure session exists
  getOrCreateSession(sessionId);

  // Fire and forget — returns immediately
  startClaudeJob(messageId, message.trim(), sessionId);

  return NextResponse.json({
    messageId,
    sessionId,
    status: "processing",
  });
}
