import { redirect } from "next/navigation";

export default function BacktestRedirect() {
  redirect("/lab?tab=backtest");
}
