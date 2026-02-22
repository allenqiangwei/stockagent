"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Trash2, ArrowUpDown } from "lucide-react";
import { RuleEditor } from "./rule-editor";
import { useIndicatorGroups } from "@/hooks/use-queries";
import type {
  Strategy,
  StrategyRule,
  IndicatorGroup,
  RankFactor,
  PortfolioConfig,
} from "@/types";

interface StrategyEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  strategy?: Strategy | null;
  onSave: (data: Omit<Strategy, "id">) => void;
}

function makeEmptyRule(
  groups: Record<string, IndicatorGroup>
): StrategyRule {
  const firstGK = Object.keys(groups)[0] ?? "RSI";
  const g = groups[firstGK];
  const params: Record<string, number> = {};
  for (const [k, v] of Object.entries(g?.params ?? {})) {
    params[k] = v.default;
  }
  return {
    field: g?.sub_fields?.[0]?.[0] ?? "RSI",
    operator: "<",
    compare_type: "value",
    compare_value: 0,
    params: Object.keys(params).length ? params : undefined,
    label: "",
  };
}

/** Combinator badge shown between rules */
function Combinator({ type }: { type: "AND" | "OR" }) {
  return (
    <div className="flex items-center justify-center py-0.5">
      <Badge
        variant="outline"
        className={`text-[10px] font-semibold px-2 py-0 ${
          type === "AND"
            ? "border-blue-500/40 text-blue-400"
            : "border-orange-500/40 text-orange-400"
        }`}
      >
        {type === "AND" ? "且 AND" : "或 OR"}
      </Badge>
    </div>
  );
}

const FACTOR_FIELDS: Record<string, [string, string][]> = {
  indicator: [
    ["RSI", "RSI"],
    ["MACD_hist", "MACD柱"],
    ["KDJ_J", "KDJ_J"],
    ["ATR", "ATR"],
    ["ADX", "ADX"],
  ],
  kline: [
    ["volume", "成交量"],
    ["close", "收盘价"],
    ["amount", "成交额"],
  ],
  basic: [
    ["total_mv", "总市值"],
    ["circ_mv", "流通市值"],
    ["pe", "市盈率"],
    ["pb", "市净率"],
    ["turnover_rate", "换手率"],
  ],
};

const FACTOR_TYPE_LABELS: Record<string, string> = {
  indicator: "技术指标",
  kline: "行情数据",
  basic: "基本面",
};

function makeEmptyFactor(): RankFactor {
  return { type: "kline", field: "volume", direction: "desc", weight: 0.25 };
}

export function StrategyEditor({
  open,
  onOpenChange,
  strategy,
  onSave,
}: StrategyEditorProps) {
  const { data: meta } = useIndicatorGroups();
  const groups = meta?.groups ?? {};
  const operators = meta?.operators ?? [];

  // Form state (no scoring rules — removed from system)
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [weight, setWeight] = useState(0.5);
  const [buyConds, setBuyConds] = useState<StrategyRule[]>([]);
  const [sellConds, setSellConds] = useState<StrategyRule[]>([]);
  const [stopLoss, setStopLoss] = useState<number | "">("");
  const [takeProfit, setTakeProfit] = useState<number | "">("");
  const [maxHoldDays, setMaxHoldDays] = useState<number | "">("");
  // Portfolio config
  const [initialCapital, setInitialCapital] = useState<number>(100000);
  const [maxPositions, setMaxPositions] = useState<number>(10);
  const [rankFactors, setRankFactors] = useState<RankFactor[]>([]);
  const [portfolioEnabled, setPortfolioEnabled] = useState(false);

  // Populate from existing strategy
  useEffect(() => {
    if (strategy) {
      setName(strategy.name);
      setDescription(strategy.description);
      setWeight(strategy.weight);
      setBuyConds(
        (strategy.buy_conditions as unknown as StrategyRule[]) ?? []
      );
      setSellConds(
        (strategy.sell_conditions as unknown as StrategyRule[]) ?? []
      );
      setStopLoss(strategy.exit_config?.stop_loss_pct ?? "");
      setTakeProfit(strategy.exit_config?.take_profit_pct ?? "");
      setMaxHoldDays(strategy.exit_config?.max_hold_days ?? "");
      // Portfolio config
      const pc = strategy.portfolio_config;
      setPortfolioEnabled(!!pc);
      setInitialCapital(pc?.initial_capital ?? 100000);
      setMaxPositions(pc?.max_positions ?? 10);
      setRankFactors(strategy.rank_config?.factors ?? []);
    } else {
      setName("");
      setDescription("");
      setWeight(0.5);
      setBuyConds([]);
      setSellConds([]);
      setStopLoss("");
      setTakeProfit("");
      setMaxHoldDays("");
      setPortfolioEnabled(false);
      setInitialCapital(100000);
      setMaxPositions(10);
      setRankFactors([]);
    }
  }, [strategy, open]);

  function handleSave() {
    const exitConfig: Record<string, number | undefined> = {};
    if (stopLoss !== "") exitConfig.stop_loss_pct = Number(stopLoss);
    if (takeProfit !== "") exitConfig.take_profit_pct = Number(takeProfit);
    if (maxHoldDays !== "") exitConfig.max_hold_days = Number(maxHoldDays);

    onSave({
      name,
      description,
      weight,
      rules: [],
      buy_conditions: buyConds as unknown as Record<string, unknown>[],
      sell_conditions: sellConds as unknown as Record<string, unknown>[],
      exit_config: exitConfig as Strategy["exit_config"],
      enabled: strategy?.enabled ?? true,
      rank_config: rankFactors.length > 0 ? { factors: rankFactors } : null,
      portfolio_config: portfolioEnabled
        ? { initial_capital: initialCapital, max_positions: maxPositions, position_sizing: "equal_weight" as const }
        : null,
    });
  }

  function updateRule<T>(list: T[], index: number, item: T): T[] {
    const next = [...list];
    next[index] = item;
    return next;
  }
  function removeRule<T>(list: T[], index: number): T[] {
    return list.filter((_, i) => i !== index);
  }

  const hasGroups = Object.keys(groups).length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[900px] w-[95vw] max-h-[90vh] flex flex-col p-0">
        <DialogHeader className="px-6 pt-5 pb-3">
          <DialogTitle className="text-base">
            {strategy ? `编辑策略 — ${strategy.name}` : "新建策略"}
          </DialogTitle>
        </DialogHeader>

        {/* Basic info */}
        <div className="px-6 pb-2">
          <div className="grid grid-cols-[1fr_1.5fr_80px] gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">
                策略名称
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="输入策略名称"
                className="h-9"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">
                策略描述
              </label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="简要描述策略逻辑"
                className="h-9"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">
                权重
              </label>
              <Input
                type="number"
                min={0}
                max={1}
                step={0.1}
                value={weight}
                onChange={(e) => setWeight(parseFloat(e.target.value) || 0)}
                className="h-9"
              />
            </div>
          </div>
        </div>

        {/* Tabs — only buy / sell / exit */}
        <Tabs defaultValue="buy" className="flex-1 min-h-0 flex flex-col">
          <div className="px-6">
            <TabsList className="w-full">
              <TabsTrigger value="buy" className="flex-1">
                买入条件 ({buyConds.length})
              </TabsTrigger>
              <TabsTrigger value="sell" className="flex-1">
                卖出条件 ({sellConds.length})
              </TabsTrigger>
              <TabsTrigger value="exit" className="flex-1">
                风控设置
              </TabsTrigger>
              <TabsTrigger value="ranking" className="flex-1">
                <ArrowUpDown className="h-3.5 w-3.5 mr-1" />
                选股排序
              </TabsTrigger>
            </TabsList>
          </div>

          {/* Buy conditions (AND) */}
          <TabsContent value="buy" className="mt-0 flex-1 min-h-0 px-6">
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm text-muted-foreground">
                全部条件同时满足时触发买入信号
              </span>
              <Badge
                variant="outline"
                className="text-[10px] border-blue-500/40 text-blue-400"
              >
                AND 逻辑
              </Badge>
            </div>
            <ScrollArea className="h-[340px]">
              <div className="space-y-0 pr-3">
                {buyConds.map((r, i) => (
                  <div key={i}>
                    {i > 0 && <Combinator type="AND" />}
                    <RuleEditor
                      rule={r}
                      onChange={(updated) =>
                        setBuyConds(updateRule(buyConds, i, updated))
                      }
                      onRemove={() => setBuyConds(removeRule(buyConds, i))}
                      groups={groups}
                      operators={operators}
                    />
                  </div>
                ))}
              </div>
              {hasGroups && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3 w-full border-dashed"
                  onClick={() =>
                    setBuyConds([...buyConds, makeEmptyRule(groups)])
                  }
                >
                  <Plus className="h-4 w-4 mr-1.5" />
                  添加买入条件
                </Button>
              )}
              {!hasGroups && (
                <div className="text-sm text-muted-foreground text-center py-8">
                  正在加载指标数据...
                </div>
              )}
            </ScrollArea>
          </TabsContent>

          {/* Sell conditions (OR) */}
          <TabsContent value="sell" className="mt-0 flex-1 min-h-0 px-6">
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm text-muted-foreground">
                任一条件满足即触发卖出信号
              </span>
              <Badge
                variant="outline"
                className="text-[10px] border-orange-500/40 text-orange-400"
              >
                OR 逻辑
              </Badge>
            </div>
            <ScrollArea className="h-[340px]">
              <div className="space-y-0 pr-3">
                {sellConds.map((r, i) => (
                  <div key={i}>
                    {i > 0 && <Combinator type="OR" />}
                    <RuleEditor
                      rule={r}
                      onChange={(updated) =>
                        setSellConds(updateRule(sellConds, i, updated))
                      }
                      onRemove={() => setSellConds(removeRule(sellConds, i))}
                      groups={groups}
                      operators={operators}
                    />
                  </div>
                ))}
              </div>
              {hasGroups && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3 w-full border-dashed"
                  onClick={() =>
                    setSellConds([...sellConds, makeEmptyRule(groups)])
                  }
                >
                  <Plus className="h-4 w-4 mr-1.5" />
                  添加卖出条件
                </Button>
              )}
              {!hasGroups && (
                <div className="text-sm text-muted-foreground text-center py-8">
                  正在加载指标数据...
                </div>
              )}
            </ScrollArea>
          </TabsContent>

          {/* Exit / risk config */}
          <TabsContent value="exit" className="mt-0 flex-1 min-h-0 px-6">
            <div className="py-2">
              <span className="text-sm text-muted-foreground">
                设置止损止盈和最长持有期限
              </span>
            </div>
            <div className="grid grid-cols-3 gap-4 max-w-lg">
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">
                  止损 (%)
                </label>
                <Input
                  type="number"
                  placeholder="-8"
                  className="h-9"
                  value={stopLoss}
                  onChange={(e) =>
                    setStopLoss(
                      e.target.value === "" ? "" : parseFloat(e.target.value)
                    )
                  }
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  负数，如 -8 表示跌8%止损
                </p>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">
                  止盈 (%)
                </label>
                <Input
                  type="number"
                  placeholder="20"
                  className="h-9"
                  value={takeProfit}
                  onChange={(e) =>
                    setTakeProfit(
                      e.target.value === "" ? "" : parseFloat(e.target.value)
                    )
                  }
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  正数，如 20 表示涨20%止盈
                </p>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">
                  最长持有 (天)
                </label>
                <Input
                  type="number"
                  placeholder="10"
                  className="h-9"
                  value={maxHoldDays}
                  onChange={(e) =>
                    setMaxHoldDays(
                      e.target.value === "" ? "" : parseInt(e.target.value, 10)
                    )
                  }
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  超出天数自动平仓
                </p>
              </div>
            </div>
          </TabsContent>

          {/* Ranking / Portfolio config */}
          <TabsContent value="ranking" className="mt-0 flex-1 min-h-0 px-6">
            <ScrollArea className="h-[380px]">
              <div className="space-y-4 pr-3">
                {/* Portfolio toggle */}
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={portfolioEnabled}
                      onChange={(e) => setPortfolioEnabled(e.target.checked)}
                      className="rounded border-gray-600"
                    />
                    启用组合回测模式
                  </label>
                  <span className="text-xs text-muted-foreground">
                    单一资金池 + 持仓上限 + 多因子选股排序
                  </span>
                </div>

                {portfolioEnabled && (
                  <>
                    {/* Portfolio params */}
                    <div className="grid grid-cols-2 gap-4 max-w-md">
                      <div>
                        <label className="text-xs text-muted-foreground mb-1.5 block">
                          初始资金
                        </label>
                        <Input
                          type="number"
                          className="h-9"
                          value={initialCapital}
                          onChange={(e) => setInitialCapital(Number(e.target.value) || 100000)}
                        />
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground mb-1.5 block">
                          最大持仓数
                        </label>
                        <Input
                          type="number"
                          min={1}
                          max={50}
                          className="h-9"
                          value={maxPositions}
                          onChange={(e) => setMaxPositions(Number(e.target.value) || 10)}
                        />
                      </div>
                    </div>

                    {/* Ranking factors */}
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-medium">排序因子</span>
                        <span className="text-xs text-muted-foreground">
                          买入信号多于空位时，按因子加权排序选优
                        </span>
                      </div>

                      <div className="space-y-2">
                        {rankFactors.map((factor, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-2 rounded-md border p-2"
                          >
                            {/* Type select */}
                            <Select
                              value={factor.type}
                              onValueChange={(v) => {
                                const next = [...rankFactors];
                                const newType = v as RankFactor["type"];
                                next[i] = {
                                  ...factor,
                                  type: newType,
                                  field: FACTOR_FIELDS[newType]?.[0]?.[0] ?? "",
                                };
                                setRankFactors(next);
                              }}
                            >
                              <SelectTrigger className="w-24 h-8 text-xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {Object.entries(FACTOR_TYPE_LABELS).map(([k, label]) => (
                                  <SelectItem key={k} value={k}>
                                    {label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>

                            {/* Field select */}
                            <Select
                              value={factor.field}
                              onValueChange={(v) => {
                                const next = [...rankFactors];
                                next[i] = { ...factor, field: v };
                                setRankFactors(next);
                              }}
                            >
                              <SelectTrigger className="w-28 h-8 text-xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {(FACTOR_FIELDS[factor.type] ?? []).map(([k, label]) => (
                                  <SelectItem key={k} value={k}>
                                    {label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>

                            {/* Direction toggle */}
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 px-2 text-xs w-14"
                              onClick={() => {
                                const next = [...rankFactors];
                                next[i] = {
                                  ...factor,
                                  direction: factor.direction === "asc" ? "desc" : "asc",
                                };
                                setRankFactors(next);
                              }}
                            >
                              {factor.direction === "asc" ? "升序" : "降序"}
                            </Button>

                            {/* Weight slider */}
                            <div className="flex-1 flex items-center gap-2">
                              <span className="text-xs text-muted-foreground w-8">权重</span>
                              <Slider
                                value={[factor.weight]}
                                onValueChange={([v]) => {
                                  const next = [...rankFactors];
                                  next[i] = { ...factor, weight: v };
                                  setRankFactors(next);
                                }}
                                min={0}
                                max={1}
                                step={0.05}
                                className="flex-1"
                              />
                              <span className="text-xs font-mono w-8">
                                {factor.weight.toFixed(2)}
                              </span>
                            </div>

                            {/* Remove */}
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0"
                              onClick={() =>
                                setRankFactors(rankFactors.filter((_, j) => j !== i))
                              }
                            >
                              <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                            </Button>
                          </div>
                        ))}
                      </div>

                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-2 w-full border-dashed"
                        onClick={() => setRankFactors([...rankFactors, makeEmptyFactor()])}
                      >
                        <Plus className="h-4 w-4 mr-1.5" />
                        添加排序因子
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={!name.trim()}>
            保存策略
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
