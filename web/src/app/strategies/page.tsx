"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useStrategies, useIndicatorGroups } from "@/hooks/use-queries";
import { strategies as strategiesApi } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import {
  Settings2,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Plus,
  Pencil,
} from "lucide-react";
import type { Strategy, StrategyRule, IndicatorGroup, RegimeStatEntry } from "@/types";
import { StrategyEditor } from "@/components/strategy/strategy-editor";

// ── Category badge colors ─────────────────────────
const CATEGORY_STYLES: Record<string, string> = {
  全能: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  牛市: "bg-green-500/15 text-green-400 border-green-500/30",
  熊市: "bg-red-500/15 text-red-400 border-red-500/30",
  震荡: "bg-amber-500/15 text-amber-400 border-amber-500/30",
};

function CategoryBadge({ category }: { category?: string | null }) {
  if (!category) {
    return <Badge variant="outline" className="text-xs border-muted-foreground/30 text-muted-foreground">手动</Badge>;
  }
  return (
    <Badge variant="outline" className={`text-xs ${CATEGORY_STYLES[category] ?? ""}`}>
      {category}
    </Badge>
  );
}

// ── AI label helpers ────────────────────────────
const AI_LABEL_RE = /^\[AI(?:-[^\]]+)?\]\s*/;

function stripAiPrefix(name: string): string {
  return name.replace(AI_LABEL_RE, "");
}

function isAiStrategy(s: Strategy): boolean {
  return s.source_experiment_id != null || AI_LABEL_RE.test(s.name);
}

// ── Human-readable rule formatting ────────────────
function fieldLabel(
  field: string,
  groups: Record<string, IndicatorGroup>
): string {
  for (const g of Object.values(groups)) {
    for (const [fk, fl] of g.sub_fields) {
      if (fk === field) return fl;
    }
  }
  return field;
}

function formatRule(
  r: StrategyRule,
  groups: Record<string, IndicatorGroup>
): string {
  if (r.label) return r.label;
  const left = fieldLabel(r.field, groups);
  const op = r.operator;
  if (r.compare_type === "field" && r.compare_field) {
    const right = fieldLabel(r.compare_field, groups);
    return `${left} ${op} ${right}`;
  }
  return `${left} ${op} ${r.compare_value ?? 0}`;
}

// ── Formatting helpers ────────────────────────────
function fmtPct(v: number | undefined | null): string {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function fmtScore(v: number | undefined | null): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

// ── Category tabs ─────────────────────────────────
const CATEGORY_TABS = [
  { value: "", label: "全部" },
  { value: "全能", label: "全能" },
  { value: "牛市", label: "牛市" },
  { value: "熊市", label: "熊市" },
  { value: "震荡", label: "震荡" },
  { value: "_manual", label: "手动" },
];

// ── Regime display name mapping ───────────────────
const REGIME_LABELS: Record<string, string> = {
  bull: "牛市",
  bear: "熊市",
  ranging: "震荡",
};

// ── Page ──────────────────────────────────────────

export default function StrategiesPage() {
  const qc = useQueryClient();
  const [activeCategory, setActiveCategory] = useState("");
  const { data: strats, isLoading } = useStrategies(activeCategory);
  const { data: meta } = useIndicatorGroups();
  const groups = meta?.groups ?? {};

  const [selectedId, setSelectedId] = useState<number>(0);
  const selectedStrategy = strats?.find((s) => s.id === selectedId) ?? null;

  // Editor dialog state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null);

  async function toggleEnabled(s: Strategy) {
    await strategiesApi.update(s.id, { enabled: !s.enabled });
    qc.invalidateQueries({ queryKey: ["strategies"] });
  }

  async function handleDelete(id: number) {
    if (!confirm("确定删除此策略？")) return;
    await strategiesApi.delete(id);
    qc.invalidateQueries({ queryKey: ["strategies"] });
    if (selectedId === id) setSelectedId(0);
  }

  function openCreate() {
    setEditingStrategy(null);
    setEditorOpen(true);
  }

  function openEdit(s: Strategy) {
    setEditingStrategy(s);
    setEditorOpen(true);
  }

  async function handleSave(data: Omit<Strategy, "id">) {
    if (editingStrategy) {
      await strategiesApi.update(editingStrategy.id, data);
    } else {
      await strategiesApi.create(data);
    }
    qc.invalidateQueries({ queryKey: ["strategies"] });
    setEditorOpen(false);
  }

  const bs = selectedStrategy?.backtest_summary;

  return (
    <div className="p-3 sm:p-4 space-y-3 sm:space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-base sm:text-lg font-semibold">
          <Settings2 className="h-5 w-5" />
          策略管理
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          新建策略
        </Button>
      </div>

      {/* Category tabs */}
      <Tabs value={activeCategory} onValueChange={setActiveCategory}>
        <TabsList variant="line">
          {CATEGORY_TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="grid lg:grid-cols-3 gap-4">
        {/* Strategy list */}
        <Card className="lg:col-span-2">
          <CardContent className="px-2 sm:px-4 py-4">
            {isLoading ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                加载中...
              </div>
            ) : !strats?.length ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                {activeCategory ? "该分类下暂无策略" : "暂无策略，点击「新建策略」开始"}
              </div>
            ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[640px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead className="w-16">分类</TableHead>
                    <TableHead className="w-14 text-right">评分</TableHead>
                    <TableHead className="w-16 text-right">收益</TableHead>
                    <TableHead className="w-16 text-right">回撤</TableHead>
                    <TableHead className="w-14 text-right">胜率</TableHead>
                    <TableHead className="w-16">状态</TableHead>
                    <TableHead className="w-28">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {strats.map((s) => {
                    const b = s.backtest_summary;
                    return (
                      <TableRow
                        key={s.id}
                        className={
                          selectedId === s.id
                            ? "bg-muted/50"
                            : "cursor-pointer hover:bg-muted/30"
                        }
                        onClick={() => setSelectedId(s.id)}
                      >
                        <TableCell className="font-medium max-w-[240px]">
                          <div className="flex items-center gap-1.5 min-w-0">
                            {isAiStrategy(s) && (
                              <Badge className="shrink-0 px-1 py-0 text-[10px] leading-4 bg-violet-500/20 text-violet-400 border border-violet-500/40 hover:bg-violet-500/20">
                                AI
                              </Badge>
                            )}
                            <span className="truncate">{stripAiPrefix(s.name)}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <CategoryBadge category={s.category} />
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {fmtScore(b?.score)}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono text-xs ${
                            b?.total_return_pct != null
                              ? b.total_return_pct > 0
                                ? "text-green-400"
                                : b.total_return_pct < 0
                                  ? "text-red-400"
                                  : ""
                              : ""
                          }`}
                        >
                          {fmtPct(b?.total_return_pct)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-red-400">
                          {b?.max_drawdown_pct != null
                            ? `${b.max_drawdown_pct.toFixed(1)}%`
                            : "—"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {b?.win_rate != null
                            ? `${(b.win_rate * 100).toFixed(0)}%`
                            : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={s.enabled ? "default" : "secondary"}>
                            {s.enabled ? "启用" : "停用"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div
                            className="flex items-center gap-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => openEdit(s)}
                              title="编辑"
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => toggleEnabled(s)}
                              title={s.enabled ? "停用" : "启用"}
                            >
                              {s.enabled ? (
                                <ToggleRight className="h-4 w-4 text-chart-1" />
                              ) : (
                                <ToggleLeft className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleDelete(s.id)}
                              title="删除"
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            )}
          </CardContent>
        </Card>

        {/* Strategy detail */}
        <Card>
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-sm">策略详情</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {!selectedStrategy ? (
              <div className="text-sm text-muted-foreground py-4 text-center">
                选择一个策略查看详情
              </div>
            ) : (
              <div className="space-y-3 text-sm">
                {/* Name + category */}
                <div>
                  <div className="text-xs text-muted-foreground">名称</div>
                  <div className="font-medium flex items-center gap-2 flex-wrap">
                    {isAiStrategy(selectedStrategy) && (
                      <Badge className="px-1.5 py-0 text-[10px] leading-4 bg-violet-500/20 text-violet-400 border border-violet-500/40 hover:bg-violet-500/20">
                        AI选
                      </Badge>
                    )}
                    {stripAiPrefix(selectedStrategy.name)}
                    <CategoryBadge category={selectedStrategy.category} />
                  </div>
                </div>

                {/* Backtest summary (only when available) */}
                {bs && (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">AI Lab 回测数据</div>
                    <div className="grid grid-cols-3 gap-x-3 gap-y-1 text-xs">
                      <div>
                        <span className="text-muted-foreground">评分 </span>
                        <span className="font-mono">{fmtScore(bs.score)}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">收益 </span>
                        <span className={`font-mono ${bs.total_return_pct > 0 ? "text-green-400" : bs.total_return_pct < 0 ? "text-red-400" : ""}`}>
                          {fmtPct(bs.total_return_pct)}
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">回撤 </span>
                        <span className="font-mono text-red-400">
                          {bs.max_drawdown_pct.toFixed(1)}%
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">胜率 </span>
                        <span className="font-mono">{(bs.win_rate * 100).toFixed(1)}%</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">交易 </span>
                        <span className="font-mono">{bs.total_trades}笔</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">持仓 </span>
                        <span className="font-mono">{bs.avg_hold_days.toFixed(1)}天</span>
                      </div>
                    </div>

                    {/* Regime stats mini-table */}
                    {bs.regime_stats && Object.keys(bs.regime_stats).length > 0 && (
                      <div className="mt-2">
                        <div className="text-xs text-muted-foreground mb-1">市场阶段表现</div>
                        <div className="space-y-0.5 text-xs">
                          {Object.entries(bs.regime_stats).map(([regime, data]: [string, RegimeStatEntry]) => (
                            <div key={regime} className="flex items-center gap-2 font-mono">
                              <span className="w-8 text-muted-foreground">{REGIME_LABELS[regime] ?? regime}</span>
                              <span className="w-12">{data.trades}笔</span>
                              <span className="w-16">胜率{(data.win_rate * 100).toFixed(0)}%</span>
                              <span className={data.total_pnl > 0 ? "text-green-400" : data.total_pnl < 0 ? "text-red-400" : ""}>
                                {data.total_pnl > 0 ? "+" : ""}{data.total_pnl.toFixed(0)}元
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div>
                  <div className="text-xs text-muted-foreground">描述</div>
                  <div>{selectedStrategy.description}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">风控设置</div>
                  <div className="grid grid-cols-1 gap-1 mt-1">
                    {selectedStrategy.exit_config?.stop_loss_pct != null && (
                      <div>
                        止损:{" "}
                        <span className="font-mono">
                          {selectedStrategy.exit_config.stop_loss_pct}%
                        </span>
                      </div>
                    )}
                    {selectedStrategy.exit_config?.take_profit_pct != null && (
                      <div>
                        止盈:{" "}
                        <span className="font-mono">
                          {selectedStrategy.exit_config.take_profit_pct}%
                        </span>
                      </div>
                    )}
                    {selectedStrategy.exit_config?.max_hold_days != null && (
                      <div>
                        最长持有:{" "}
                        <span className="font-mono">
                          {selectedStrategy.exit_config.max_hold_days}天
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Buy conditions as badges */}
                <div>
                  <div className="text-xs text-muted-foreground">
                    买入条件 AND ({selectedStrategy.buy_conditions?.length ?? 0})
                  </div>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(selectedStrategy.buy_conditions as unknown as StrategyRule[])?.map(
                      (r, i) => (
                        <Badge
                          key={i}
                          variant="outline"
                          className="text-xs font-normal border-green-600/40 text-green-500"
                        >
                          {formatRule(r, groups)}
                        </Badge>
                      )
                    )}
                    {!selectedStrategy.buy_conditions?.length && (
                      <span className="text-muted-foreground">无</span>
                    )}
                  </div>
                </div>

                {/* Sell conditions as badges */}
                <div>
                  <div className="text-xs text-muted-foreground">
                    卖出条件 OR ({selectedStrategy.sell_conditions?.length ?? 0})
                  </div>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(selectedStrategy.sell_conditions as unknown as StrategyRule[])?.map(
                      (r, i) => (
                        <Badge
                          key={i}
                          variant="outline"
                          className="text-xs font-normal border-red-600/40 text-red-500"
                        >
                          {formatRule(r, groups)}
                        </Badge>
                      )
                    )}
                    {!selectedStrategy.sell_conditions?.length && (
                      <span className="text-muted-foreground">无</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Editor dialog */}
      <StrategyEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        strategy={editingStrategy}
        onSave={handleSave}
      />
    </div>
  );
}
