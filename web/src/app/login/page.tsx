"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { KeyRound } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [key, setKey] = useState("pTSAWda_h_K6mPmgXPvunWRFkJc3LOh-5pdpsNg-ggg");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) return;

    setLoading(true);
    setError("");

    try {
      // Validate key against health-like endpoint
      const res = await fetch("/api/ai/reports?limit=1", {
        headers: { Authorization: `Bearer ${trimmed}` },
      });
      if (res.status === 401) {
        setError("API Key 无效或已吊销");
        setLoading(false);
        return;
      }
      // Store and redirect
      localStorage.setItem("stockagent_api_key", trimmed);
      router.replace("/");
    } catch {
      setError("无法连接服务器");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <KeyRound className="h-5 w-5" />
            StockAgent 登录
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            输入 API Key 访问系统
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="password"
              placeholder="粘贴 API Key..."
              value={key}
              onChange={(e) => setKey(e.target.value)}
              autoFocus
            />
            {error && (
              <p className="text-sm text-red-400">{error}</p>
            )}
            <Button type="submit" className="w-full" disabled={loading || !key.trim()}>
              {loading ? "验证中..." : "登录"}
            </Button>
            <p className="text-xs text-muted-foreground text-center">
              Key 仅存储在浏览器本地，不会上传
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
