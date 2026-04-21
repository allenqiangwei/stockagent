import { redirect } from "next/navigation";

export default function StrategiesRedirect() {
  redirect("/lab?tab=pool");
}
