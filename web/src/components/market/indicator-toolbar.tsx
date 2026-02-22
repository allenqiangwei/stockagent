"use client";

import { useState } from "react";
import { useAppStore, type IndicatorKey, type MAParams, type EMAParams, type RSIParams, type MACDParams, type KDJParams, type ADXParams, type ATRParams } from "@/lib/store";
import { INDICATOR_META } from "@/lib/indicator-meta";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const INDICATOR_KEYS: IndicatorKey[] = ["MA", "EMA", "MACD", "RSI", "KDJ", "ADX", "OBV", "ATR"];

// Colors for the pill labels when enabled
const PILL_COLORS: Record<IndicatorKey, string> = {
  MA: "bg-white/10 text-white",
  EMA: "bg-sky-500/15 text-sky-300",
  MACD: "bg-amber-500/15 text-amber-300",
  RSI: "bg-amber-500/15 text-amber-300",
  KDJ: "bg-purple-500/15 text-purple-300",
  ADX: "bg-amber-500/15 text-amber-300",
  OBV: "bg-blue-500/15 text-blue-300",
  ATR: "bg-amber-500/15 text-amber-300",
};

export function IndicatorToolbar() {
  return (
    <div className="flex items-center gap-1">
      {INDICATOR_KEYS.map((key) => (
        <IndicatorPill key={key} indicatorKey={key} />
      ))}
    </div>
  );
}

function IndicatorPill({ indicatorKey }: { indicatorKey: IndicatorKey }) {
  const [open, setOpen] = useState(false);
  const indicator = useAppStore((s) => s.indicators[indicatorKey]);
  const toggle = useAppStore((s) => s.toggleIndicator);
  const meta = INDICATOR_META[indicatorKey];

  const handleClick = () => {
    if (!indicator.enabled) {
      toggle(indicatorKey);
    } else {
      setOpen(true);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          onClick={handleClick}
          className={cn(
            "px-2 py-0.5 rounded text-xs font-medium transition-colors",
            indicator.enabled
              ? PILL_COLORS[indicatorKey]
              : "text-muted-foreground/60 hover:text-muted-foreground"
          )}
        >
          {meta.label}
        </button>
      </PopoverTrigger>
      {indicator.enabled && (
        <PopoverContent className="w-52 p-3" align="start">
          <ParamEditor indicatorKey={indicatorKey} onClose={() => setOpen(false)} />
        </PopoverContent>
      )}
    </Popover>
  );
}

// ── Parameter editors per indicator type ──

function ParamEditor({ indicatorKey, onClose }: { indicatorKey: IndicatorKey; onClose: () => void }) {
  const indicator = useAppStore((s) => s.indicators[indicatorKey]);
  const setParams = useAppStore((s) => s.setIndicatorParams);
  const toggle = useAppStore((s) => s.toggleIndicator);

  const handleDisable = () => {
    toggle(indicatorKey);
    onClose();
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{INDICATOR_META[indicatorKey].label} 参数</span>
        <button
          onClick={handleDisable}
          className="text-muted-foreground hover:text-destructive transition-colors"
          title="关闭指标"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {indicatorKey === "MA" && (
        <MAParamEditor
          params={indicator.params as MAParams}
          onChange={(p) => setParams(indicatorKey, p)}
        />
      )}
      {indicatorKey === "EMA" && (
        <EMAParamEditor
          params={indicator.params as EMAParams}
          onChange={(p) => setParams(indicatorKey, p)}
        />
      )}
      {indicatorKey === "RSI" && (
        <NumberParamEditor
          label="周期"
          value={(indicator.params as RSIParams).period}
          onChange={(v) => setParams(indicatorKey, { period: v })}
        />
      )}
      {indicatorKey === "MACD" && (
        <MACDParamEditor
          params={indicator.params as MACDParams}
          onChange={(p) => setParams(indicatorKey, p)}
        />
      )}
      {indicatorKey === "KDJ" && (
        <KDJParamEditor
          params={indicator.params as KDJParams}
          onChange={(p) => setParams(indicatorKey, p)}
        />
      )}
      {indicatorKey === "ADX" && (
        <NumberParamEditor
          label="周期"
          value={(indicator.params as ADXParams).period}
          onChange={(v) => setParams(indicatorKey, { period: v })}
        />
      )}
      {indicatorKey === "ATR" && (
        <NumberParamEditor
          label="周期"
          value={(indicator.params as ATRParams).period}
          onChange={(v) => setParams(indicatorKey, { period: v })}
        />
      )}
      {indicatorKey === "OBV" && (
        <div className="text-xs text-muted-foreground">无可调参数</div>
      )}
    </div>
  );
}

// ── MA: checkbox list ──

const MA_OPTIONS = [5, 10, 20, 60, 120, 250];

function MAParamEditor({ params, onChange }: { params: MAParams; onChange: (p: MAParams) => void }) {
  const togglePeriod = (period: number) => {
    const periods = params.periods.includes(period)
      ? params.periods.filter((p) => p !== period)
      : [...params.periods, period].sort((a, b) => a - b);
    onChange({ periods });
  };

  return (
    <div className="grid grid-cols-3 gap-1.5">
      {MA_OPTIONS.map((p) => (
        <label key={p} className="flex items-center gap-1.5 text-xs cursor-pointer">
          <Checkbox
            checked={params.periods.includes(p)}
            onCheckedChange={() => togglePeriod(p)}
            className="h-3.5 w-3.5"
          />
          MA{p}
        </label>
      ))}
    </div>
  );
}

// ── EMA: checkbox list ──

const EMA_OPTIONS = [12, 26, 50];

function EMAParamEditor({ params, onChange }: { params: EMAParams; onChange: (p: EMAParams) => void }) {
  const togglePeriod = (period: number) => {
    const periods = params.periods.includes(period)
      ? params.periods.filter((p) => p !== period)
      : [...params.periods, period].sort((a, b) => a - b);
    onChange({ periods });
  };

  return (
    <div className="grid grid-cols-3 gap-1.5">
      {EMA_OPTIONS.map((p) => (
        <label key={p} className="flex items-center gap-1.5 text-xs cursor-pointer">
          <Checkbox
            checked={params.periods.includes(p)}
            onCheckedChange={() => togglePeriod(p)}
            className="h-3.5 w-3.5"
          />
          EMA{p}
        </label>
      ))}
    </div>
  );
}

// ── MACD: three number inputs ──

function MACDParamEditor({ params, onChange }: { params: MACDParams; onChange: (p: MACDParams) => void }) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      <div>
        <div className="text-[10px] text-muted-foreground mb-0.5">快线</div>
        <Input
          type="number"
          value={params.fast}
          onChange={(e) => onChange({ ...params, fast: +e.target.value || 12 })}
          className="h-6 text-xs px-1.5"
        />
      </div>
      <div>
        <div className="text-[10px] text-muted-foreground mb-0.5">慢线</div>
        <Input
          type="number"
          value={params.slow}
          onChange={(e) => onChange({ ...params, slow: +e.target.value || 26 })}
          className="h-6 text-xs px-1.5"
        />
      </div>
      <div>
        <div className="text-[10px] text-muted-foreground mb-0.5">信号</div>
        <Input
          type="number"
          value={params.signal}
          onChange={(e) => onChange({ ...params, signal: +e.target.value || 9 })}
          className="h-6 text-xs px-1.5"
        />
      </div>
    </div>
  );
}

// ── KDJ: three number inputs ──

function KDJParamEditor({ params, onChange }: { params: KDJParams; onChange: (p: KDJParams) => void }) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      <div>
        <div className="text-[10px] text-muted-foreground mb-0.5">N</div>
        <Input
          type="number"
          value={params.n}
          onChange={(e) => onChange({ ...params, n: +e.target.value || 9 })}
          className="h-6 text-xs px-1.5"
        />
      </div>
      <div>
        <div className="text-[10px] text-muted-foreground mb-0.5">M1</div>
        <Input
          type="number"
          value={params.m1}
          onChange={(e) => onChange({ ...params, m1: +e.target.value || 3 })}
          className="h-6 text-xs px-1.5"
        />
      </div>
      <div>
        <div className="text-[10px] text-muted-foreground mb-0.5">M2</div>
        <Input
          type="number"
          value={params.m2}
          onChange={(e) => onChange({ ...params, m2: +e.target.value || 3 })}
          className="h-6 text-xs px-1.5"
        />
      </div>
    </div>
  );
}

// ── Single number input ──

function NumberParamEditor({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(+e.target.value || value)}
        className="h-6 w-16 text-xs px-1.5"
      />
    </div>
  );
}
