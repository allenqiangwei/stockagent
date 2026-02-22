import { NextRequest, NextResponse } from "next/server";
import { getJob } from "@/lib/claude-worker";

export async function GET(req: NextRequest) {
  const messageId = req.nextUrl.searchParams.get("messageId");

  if (!messageId) {
    return NextResponse.json(
      { error: "messageId is required" },
      { status: 400 },
    );
  }

  const job = getJob(messageId);

  if (!job) {
    return NextResponse.json(
      { error: "Job not found" },
      { status: 404 },
    );
  }

  return NextResponse.json({
    status: job.status,
    progress: job.progress,
    content: job.content,
    errorMessage: job.errorMessage,
    sessionId: job.sessionId,
  });
}
