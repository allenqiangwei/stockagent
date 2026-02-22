import { NextRequest, NextResponse } from "next/server";
import { getAnalysisJob } from "@/lib/claude-worker";

export async function GET(req: NextRequest) {
  const jobId = req.nextUrl.searchParams.get("jobId");

  if (!jobId) {
    return NextResponse.json(
      { error: "jobId is required" },
      { status: 400 },
    );
  }

  const job = getAnalysisJob(jobId);

  if (!job) {
    return NextResponse.json(
      { error: "Job not found" },
      { status: 404 },
    );
  }

  return NextResponse.json({
    status: job.status,
    progress: job.progress,
    reportId: job.status === "completed" ? Number(job.content) || null : null,
    errorMessage: job.errorMessage,
  });
}
