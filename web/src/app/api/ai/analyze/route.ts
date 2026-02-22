import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import { startAnalysisJob } from "@/lib/claude-worker";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const date = (body.date as string) || new Date().toISOString().slice(0, 10);

  const jobId = `analysis-${randomUUID()}`;

  startAnalysisJob(jobId, date);

  return NextResponse.json({
    jobId,
    reportDate: date,
    status: "processing",
  });
}
