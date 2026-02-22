"use client";

import { useEffect, useState } from "react";
import { useConfig, useUpdateConfig } from "@/hooks/use-queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import {
  Database,
  Clock,
  Shield,
  Save,
  CheckCircle2,
  Loader2,
  BrainCircuit,
  FlaskConical,
} from "lucide-react";

const DS_CATEGORIES = [
  { key: "realtime_quotes", label: "实时行情" },
  { key: "historical_daily", label: "历史日线" },
  { key: "index_data", label: "指数数据" },
  { key: "sector_data", label: "行业板块" },
  { key: "money_flow", label: "资金流向" },
  { key: "stock_list", label: "股票列表" },
] as const;

type DSKey = (typeof DS_CATEGORIES)[number]["key"];

interface FormState {
  ds: Record<DSKey, string>;
  fallback_enabled: boolean;
  tushare_token: string;
  tushare_rate_limit: number;
  auto_refresh_hour: number;
  auto_refresh_minute: number;
  fixed_stop_pct: number;
  atr_multiplier: number;
  max_position_pct: number;
  target_total_pct: number;
  max_stocks: number;
  deepseek_api_key: string;
  deepseek_base_url: string;
  deepseek_model: string;
  // AI Lab scoring weights
  weight_return: number;
  weight_drawdown: number;
  weight_sharpe: number;
  weight_plr: number;
}

const DEFAULTS: FormState = {
  ds: {
    realtime_quotes: "tushare",
    historical_daily: "tushare",
    index_data: "tushare",
    sector_data: "tushare",
    money_flow: "tushare",
    stock_list: "tushare",
  },
  fallback_enabled: true,
  tushare_token: "",
  tushare_rate_limit: 190,
  auto_refresh_hour: 19,
  auto_refresh_minute: 0,
  fixed_stop_pct: 0.05,
  atr_multiplier: 2.0,
  max_position_pct: 0.25,
  target_total_pct: 0.6,
  max_stocks: 10,
  deepseek_api_key: "",
  deepseek_base_url: "https://api.deepseek.com/v1",
  deepseek_model: "deepseek-chat",
  weight_return: 0.30,
  weight_drawdown: 0.25,
  weight_sharpe: 0.25,
  weight_plr: 0.20,
};

export default function SettingsPage() {
  const { data: config, isLoading } = useConfig();
  const mutation = useUpdateConfig();

  const [form, setForm] = useState<FormState>(DEFAULTS);
  const [tokenMasked, setTokenMasked] = useState("");
  const [deepseekKeyMasked, setDeepseekKeyMasked] = useState("");
  const [saved, setSaved] = useState(false);

  // Initialize form from server data once
  useEffect(() => {
    if (!config) return;
    setForm({
      ds: {
        realtime_quotes: config.data_sources.realtime_quotes,
        historical_daily: config.data_sources.historical_daily,
        index_data: config.data_sources.index_data,
        sector_data: config.data_sources.sector_data,
        money_flow: config.data_sources.money_flow,
        stock_list: config.data_sources.stock_list,
      },
      fallback_enabled: config.data_sources.fallback_enabled,
      tushare_token: "",
      tushare_rate_limit: config.data_sources.tushare_rate_limit,
      auto_refresh_hour: config.signals.auto_refresh_hour,
      auto_refresh_minute: config.signals.auto_refresh_minute,
      fixed_stop_pct: config.risk_control.fixed_stop_pct,
      atr_multiplier: config.risk_control.atr_multiplier,
      max_position_pct: config.risk_control.max_position_pct,
      target_total_pct: config.risk_control.target_total_pct,
      max_stocks: config.risk_control.max_stocks,
      deepseek_api_key: "",
      deepseek_base_url: config.deepseek.base_url,
      deepseek_model: config.deepseek.model,
      weight_return: config.ai_lab?.weight_return ?? 0.30,
      weight_drawdown: config.ai_lab?.weight_drawdown ?? 0.25,
      weight_sharpe: config.ai_lab?.weight_sharpe ?? 0.25,
      weight_plr: config.ai_lab?.weight_plr ?? 0.20,
    });
    setTokenMasked(config.data_sources.tushare_token_masked);
    setDeepseekKeyMasked(config.deepseek.api_key_masked);
  }, [config]);

  const setDS = (key: DSKey, value: string) =>
    setForm((f) => ({ ...f, ds: { ...f.ds, [key]: value } }));

  const setAllDS = (value: string) =>
    setForm((f) => ({
      ...f,
      ds: Object.fromEntries(DS_CATEGORIES.map((c) => [c.key, value])) as Record<DSKey, string>,
    }));

  const setRecommended = () =>
    setForm((f) => ({
      ...f,
      ds: {
        realtime_quotes: "tushare",
        historical_daily: "tushare",
        index_data: "tushare",
        sector_data: "akshare",
        money_flow: "akshare",
        stock_list: "tushare",
      },
    }));

  const handleSave = () => {
    setSaved(false);
    mutation.mutate(
      {
        data_sources: {
          ...form.ds,
          fallback_enabled: form.fallback_enabled,
          tushare_token: form.tushare_token,
          tushare_rate_limit: form.tushare_rate_limit,
        },
        signals: {
          auto_refresh_hour: form.auto_refresh_hour,
          auto_refresh_minute: form.auto_refresh_minute,
        },
        risk_control: {
          fixed_stop_pct: form.fixed_stop_pct,
          atr_multiplier: form.atr_multiplier,
          max_position_pct: form.max_position_pct,
          target_total_pct: form.target_total_pct,
          max_stocks: form.max_stocks,
        },
        deepseek: {
          api_key: form.deepseek_api_key,
          base_url: form.deepseek_base_url,
          model: form.deepseek_model,
        },
        ai_lab: {
          weight_return: form.weight_return,
          weight_drawdown: form.weight_drawdown,
          weight_sharpe: form.weight_sharpe,
          weight_plr: form.weight_plr,
        },
      },
      {
        onSuccess: () => {
          setSaved(true);
          setForm((f) => ({ ...f, tushare_token: "", deepseek_api_key: "" }));
          setTimeout(() => setSaved(false), 3000);
        },
      }
    );
  };

  const nextRun = (() => {
    const now = new Date();
    const target = new Date(now);
    target.setHours(form.auto_refresh_hour, form.auto_refresh_minute, 0, 0);
    if (now >= target) target.setDate(target.getDate() + 1);
    return target.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  })();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-5 sm:space-y-6 max-w-3xl mx-auto px-3 sm:px-4 py-4 sm:py-0">
      <h1 className="text-lg sm:text-xl font-semibold">系统设置</h1>

      {/* Card 1: Data Source Config */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" />
            数据源配置
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {DS_CATEGORIES.map(({ key, label }) => (
              <div key={key} className="flex items-center justify-between gap-2">
                <span className="text-sm text-muted-foreground">{label}</span>
                <Select value={form.ds[key]} onValueChange={(v) => setDS(key, v)}>
                  <SelectTrigger className="w-[130px] h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tushare">TuShare</SelectItem>
                    <SelectItem value="akshare">AkShare</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={() => setAllDS("tushare")}>
              全部 TuShare
            </Button>
            <Button variant="outline" size="sm" onClick={() => setAllDS("akshare")}>
              全部 AkShare
            </Button>
            <Button variant="outline" size="sm" onClick={setRecommended}>
              推荐配置
            </Button>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <Checkbox
              id="fallback"
              checked={form.fallback_enabled}
              onCheckedChange={(v) =>
                setForm((f) => ({ ...f, fallback_enabled: v === true }))
              }
            />
            <label htmlFor="fallback" className="text-sm cursor-pointer">
              启用备用数据源（主数据源失败时自动切换）
            </label>
          </div>
        </CardContent>
      </Card>

      {/* Card 2: TuShare Config */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">TuShare 配置</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">当前 Token</span>
            <Badge variant="secondary" className="font-mono text-xs">
              {tokenMasked || "未设置"}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">新 Token</span>
            <Input
              type="password"
              placeholder="留空则不更改"
              value={form.tushare_token}
              onChange={(e) =>
                setForm((f) => ({ ...f, tushare_token: e.target.value }))
              }
              className="h-8 font-mono text-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">频率限制</span>
            <Input
              type="number"
              min={1}
              max={500}
              value={form.tushare_rate_limit}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  tushare_rate_limit: parseInt(e.target.value) || 190,
                }))
              }
              className="h-8 w-24"
            />
            <span className="text-sm text-muted-foreground">次/分钟</span>
          </div>
        </CardContent>
      </Card>

      {/* Card 3: DeepSeek Config */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BrainCircuit className="h-4 w-4" />
            DeepSeek AI 配置
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">当前 Key</span>
            <Badge variant="secondary" className="font-mono text-xs">
              {deepseekKeyMasked || "未设置"}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">API Key</span>
            <Input
              type="password"
              placeholder="留空则不更改"
              value={form.deepseek_api_key}
              onChange={(e) =>
                setForm((f) => ({ ...f, deepseek_api_key: e.target.value }))
              }
              className="h-8 font-mono text-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">Base URL</span>
            <Input
              placeholder="https://api.deepseek.com/v1"
              value={form.deepseek_base_url}
              onChange={(e) =>
                setForm((f) => ({ ...f, deepseek_base_url: e.target.value }))
              }
              className="h-8 font-mono text-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground w-20 shrink-0">模型</span>
            <Select
              value={form.deepseek_model}
              onValueChange={(v) =>
                setForm((f) => ({ ...f, deepseek_model: v }))
              }
            >
              <SelectTrigger className="w-[200px] h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="deepseek-chat">deepseek-chat</SelectItem>
                <SelectItem value="deepseek-reasoner">deepseek-reasoner</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p className="text-xs text-muted-foreground">
            用于 AI 策略实验室的策略生成，需要 DeepSeek API Key 才能使用
          </p>
        </CardContent>
      </Card>

      {/* Card 4: AI Lab Scoring Weights */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <FlaskConical className="h-4 w-4" />
            AI 实验室评分权重
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">
            调整策略评分的四个维度权重，总和应为 1.0。影响新实验的策略排名。
          </p>
          {([
            { key: "weight_return" as const, label: "收益率", desc: "总收益率得分权重" },
            { key: "weight_drawdown" as const, label: "最大回撤", desc: "回撤控制得分权重" },
            { key: "weight_sharpe" as const, label: "Sharpe", desc: "风险调整收益权重" },
            { key: "weight_plr" as const, label: "盈亏比", desc: "平均盈利/亏损比权重" },
          ]).map(({ key, label, desc }) => (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-sm">{label}</span>
                <span className="text-sm font-mono text-muted-foreground w-12 text-right">
                  {(form[key] * 100).toFixed(0)}%
                </span>
              </div>
              <Slider
                min={0}
                max={100}
                step={5}
                value={[Math.round(form[key] * 100)]}
                onValueChange={([v]) =>
                  setForm((f) => ({ ...f, [key]: v / 100 }))
                }
              />
              <p className="text-xs text-muted-foreground">{desc}</p>
            </div>
          ))}
          <div className="flex items-center justify-between pt-1 border-t">
            <span className="text-sm font-medium">总和</span>
            <span
              className={`text-sm font-mono ${
                Math.abs(
                  form.weight_return +
                    form.weight_drawdown +
                    form.weight_sharpe +
                    form.weight_plr -
                    1.0
                ) < 0.01
                  ? "text-green-500"
                  : "text-red-500"
              }`}
            >
              {(
                (form.weight_return +
                  form.weight_drawdown +
                  form.weight_sharpe +
                  form.weight_plr) *
                100
              ).toFixed(0)}
              %
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Card 5: Signal Schedule */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4" />
            信号自动刷新
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">时</span>
            <Input
              type="number"
              min={0}
              max={23}
              value={form.auto_refresh_hour}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  auto_refresh_hour: parseInt(e.target.value) || 0,
                }))
              }
              className="h-8 w-20"
            />
            <span className="text-sm text-muted-foreground">分</span>
            <Input
              type="number"
              min={0}
              max={59}
              value={form.auto_refresh_minute}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  auto_refresh_minute: parseInt(e.target.value) || 0,
                }))
              }
              className="h-8 w-20"
            />
          </div>
          <p className="text-xs text-muted-foreground">
            下次执行: {nextRun}
          </p>
        </CardContent>
      </Card>

      {/* Card 4: Risk Control */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Shield className="h-4 w-4" />
            风控参数
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">固定止损 (%)</label>
              <Input
                type="number"
                step={0.01}
                min={0}
                max={1}
                value={form.fixed_stop_pct}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    fixed_stop_pct: parseFloat(e.target.value) || 0,
                  }))
                }
                className="h-8"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">ATR 倍数</label>
              <Input
                type="number"
                step={0.1}
                min={0.5}
                max={10}
                value={form.atr_multiplier}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    atr_multiplier: parseFloat(e.target.value) || 2.0,
                  }))
                }
                className="h-8"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">最大单股仓位 (%)</label>
              <Input
                type="number"
                step={0.01}
                min={0}
                max={1}
                value={form.max_position_pct}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    max_position_pct: parseFloat(e.target.value) || 0,
                  }))
                }
                className="h-8"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">目标总仓位 (%)</label>
              <Input
                type="number"
                step={0.01}
                min={0}
                max={1}
                value={form.target_total_pct}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    target_total_pct: parseFloat(e.target.value) || 0,
                  }))
                }
                className="h-8"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">最大持股数</label>
              <Input
                type="number"
                min={1}
                max={50}
                value={form.max_stocks}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    max_stocks: parseInt(e.target.value) || 10,
                  }))
                }
                className="h-8"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={mutation.isPending}>
          {mutation.isPending ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          保存设置
        </Button>
        {saved && (
          <span className="flex items-center gap-1 text-sm text-green-500">
            <CheckCircle2 className="h-4 w-4" />
            保存成功
          </span>
        )}
        {mutation.isError && (
          <span className="text-sm text-destructive">
            保存失败: {mutation.error?.message}
          </span>
        )}
      </div>
    </div>
  );
}
