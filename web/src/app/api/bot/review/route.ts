import { NextResponse } from "next/server";
import { startReviewJob } from "@/lib/claude-worker";

export async function POST(req: Request) {
  try {
    const { reviewId, stockCode, stockName, trades, pnl, pnlPct } = await req.json();

    if (!reviewId || !stockCode) {
      return NextResponse.json({ error: "Missing reviewId or stockCode" }, { status: 400 });
    }

    const tradesJson = JSON.stringify(trades, null, 2);
    const jobId = startReviewJob(reviewId, stockCode, stockName, tradesJson, pnl, pnlPct);

    return NextResponse.json({ jobId, status: "started" });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
