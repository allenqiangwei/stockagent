"use client";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";
import type { IndicatorGroup, StrategyRule } from "@/types";

interface RuleEditorProps {
  rule: StrategyRule;
  onChange: (rule: StrategyRule) => void;
  onRemove: () => void;
  groups: Record<string, IndicatorGroup>;
  operators: [string, string][];
}

/** Find which group a field belongs to */
function findGroup(
  field: string,
  groups: Record<string, IndicatorGroup>
): string {
  for (const [gk, g] of Object.entries(groups)) {
    if (g.sub_fields.some(([fk]) => fk === field)) return gk;
  }
  return "";
}

/** Build default params for a group */
function defaultParams(group: IndicatorGroup): Record<string, number> {
  const p: Record<string, number> = {};
  for (const [k, v] of Object.entries(group.params)) {
    p[k] = v.default;
  }
  return p;
}

/** Auto-generate a label from the rule definition */
function autoLabel(
  rule: StrategyRule,
  groups: Record<string, IndicatorGroup>
): string {
  const gk = findGroup(rule.field, groups);
  const g = gk ? groups[gk] : null;
  const fieldLabel =
    g?.sub_fields.find(([fk]) => fk === rule.field)?.[1] ?? rule.field;

  // Append params if non-default
  let leftStr = fieldLabel;
  if (g && rule.params) {
    const defs = defaultParams(g);
    const nonDefault = Object.entries(rule.params).filter(
      ([k, v]) => defs[k] !== undefined && defs[k] !== v
    );
    if (nonDefault.length > 0) {
      leftStr += `(${nonDefault.map(([, v]) => v).join(",")})`;
    }
  }

  const op = rule.operator;

  if (rule.compare_type === "field" && rule.compare_field) {
    const cgk = findGroup(rule.compare_field, groups);
    const cg = cgk ? groups[cgk] : null;
    const cLabel =
      cg?.sub_fields.find(([fk]) => fk === rule.compare_field)?.[1] ??
      rule.compare_field;
    let rightStr = cLabel;
    if (cg && rule.compare_params) {
      const defs = defaultParams(cg);
      const nonDefault = Object.entries(rule.compare_params).filter(
        ([k, v]) => defs[k] !== undefined && defs[k] !== v
      );
      if (nonDefault.length > 0) {
        rightStr += `(${nonDefault.map(([, v]) => v).join(",")})`;
      }
    }
    return `${leftStr} ${op} ${rightStr}`;
  }
  return `${leftStr} ${op} ${rule.compare_value ?? 0}`;
}

export function RuleEditor({
  rule,
  onChange,
  onRemove,
  groups,
  operators,
}: RuleEditorProps) {
  const groupKey = findGroup(rule.field, groups);
  const group = groupKey ? groups[groupKey] : null;

  const compareGroupKey =
    rule.compare_type === "field" && rule.compare_field
      ? findGroup(rule.compare_field, groups)
      : "";
  const compareGroup = compareGroupKey ? groups[compareGroupKey] : null;

  // -- Handlers --

  function handleGroupChange(newGroupKey: string) {
    const g = groups[newGroupKey];
    if (!g) return;
    const firstField = g.sub_fields[0][0];
    const params = defaultParams(g);
    const updated: StrategyRule = {
      ...rule,
      field: firstField,
      params: Object.keys(params).length ? params : undefined,
    };
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleFieldChange(newField: string) {
    const updated = { ...rule, field: newField };
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleOperatorChange(op: string) {
    const updated = { ...rule, operator: op };
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleCompareTypeChange(ct: "value" | "field") {
    let updated: StrategyRule;
    if (ct === "value") {
      updated = {
        ...rule,
        compare_type: "value",
        compare_value: 0,
        compare_field: undefined,
        compare_params: undefined,
      };
    } else {
      const firstGK = Object.keys(groups)[0];
      const firstG = groups[firstGK];
      updated = {
        ...rule,
        compare_type: "field",
        compare_value: undefined,
        compare_field: firstG.sub_fields[0][0],
        compare_params: Object.keys(firstG.params).length
          ? defaultParams(firstG)
          : undefined,
      };
    }
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleCompareGroupChange(newGroupKey: string) {
    const g = groups[newGroupKey];
    if (!g) return;
    const params = defaultParams(g);
    const updated: StrategyRule = {
      ...rule,
      compare_field: g.sub_fields[0][0],
      compare_params: Object.keys(params).length ? params : undefined,
    };
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleCompareFieldChange(newField: string) {
    const updated = { ...rule, compare_field: newField };
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleCompareValueChange(val: string) {
    const v = parseFloat(val);
    const updated = { ...rule, compare_value: isNaN(v) ? 0 : v };
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  function handleParamChange(
    key: string,
    val: string,
    side: "left" | "right"
  ) {
    const num = parseInt(val, 10);
    if (isNaN(num)) return;
    let updated: StrategyRule;
    if (side === "left") {
      updated = { ...rule, params: { ...(rule.params ?? {}), [key]: num } };
    } else {
      updated = {
        ...rule,
        compare_params: { ...(rule.compare_params ?? {}), [key]: num },
      };
    }
    onChange({ ...updated, label: autoLabel(updated, groups) });
  }

  // Operator label lookup
  const opLabel = operators.find(([op]) => op === rule.operator)?.[1] ?? rule.operator;

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      {/* Row 1: Main condition sentence */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <span className="text-xs text-muted-foreground shrink-0">当</span>

        {/* Left: indicator group */}
        <Select value={groupKey} onValueChange={handleGroupChange}>
          <SelectTrigger className="w-[110px] h-8 text-sm">
            <SelectValue placeholder="选择指标" />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(groups).map(([gk, g]) => (
              <SelectItem key={gk} value={gk}>
                {g.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Left: sub field */}
        {group && group.sub_fields.length > 1 && (
          <Select value={rule.field} onValueChange={handleFieldChange}>
            <SelectTrigger className="w-[120px] h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {group.sub_fields.map(([fk, fl]) => (
                <SelectItem key={fk} value={fk}>
                  {fl}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Operator */}
        <Select value={rule.operator} onValueChange={handleOperatorChange}>
          <SelectTrigger className="w-[100px] h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {operators.map(([op, label]) => (
              <SelectItem key={op} value={op}>
                {op} {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Compare type */}
        <Select
          value={rule.compare_type}
          onValueChange={(v) =>
            handleCompareTypeChange(v as "value" | "field")
          }
        >
          <SelectTrigger className="w-[100px] h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="value">固定值</SelectItem>
            <SelectItem value="field">另一指标</SelectItem>
          </SelectContent>
        </Select>

        {/* Right side: value or field */}
        {rule.compare_type === "value" ? (
          <Input
            type="number"
            className="w-[80px] h-8 text-sm text-center"
            value={rule.compare_value ?? 0}
            onChange={(e) => handleCompareValueChange(e.target.value)}
          />
        ) : (
          <>
            <Select
              value={compareGroupKey}
              onValueChange={handleCompareGroupChange}
            >
              <SelectTrigger className="w-[110px] h-8 text-sm">
                <SelectValue placeholder="选择指标" />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(groups).map(([gk, g]) => (
                  <SelectItem key={gk} value={gk}>
                    {g.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {compareGroup && compareGroup.sub_fields.length > 1 && (
              <Select
                value={rule.compare_field ?? ""}
                onValueChange={handleCompareFieldChange}
              >
                <SelectTrigger className="w-[120px] h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {compareGroup.sub_fields.map(([fk, fl]) => (
                    <SelectItem key={fk} value={fk}>
                      {fl}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </>
        )}

        {/* Remove button */}
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 shrink-0 ml-auto"
          onClick={onRemove}
        >
          <X className="h-4 w-4 text-muted-foreground hover:text-destructive" />
        </Button>
      </div>

      {/* Row 2: Parameters + Label */}
      <div className="flex flex-wrap items-center gap-3 px-3 py-2 border-t border-border/40 bg-muted/20">
        {/* Left params */}
        {group && Object.keys(group.params).length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">参数:</span>
            {Object.entries(group.params).map(([pk, pv]) => (
              <div key={pk} className="flex items-center gap-0.5">
                <span className="text-xs text-muted-foreground">
                  {pv.label}
                </span>
                <Input
                  type="number"
                  className="w-[56px] h-7 text-xs text-center"
                  value={rule.params?.[pk] ?? pv.default}
                  onChange={(e) =>
                    handleParamChange(pk, e.target.value, "left")
                  }
                />
              </div>
            ))}
          </div>
        )}

        {/* Right params (for field comparison) */}
        {rule.compare_type === "field" &&
          compareGroup &&
          Object.keys(compareGroup.params).length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">比较参数:</span>
              {Object.entries(compareGroup.params).map(([pk, pv]) => (
                <div key={pk} className="flex items-center gap-0.5">
                  <span className="text-xs text-muted-foreground">
                    {pv.label}
                  </span>
                  <Input
                    type="number"
                    className="w-[56px] h-7 text-xs text-center"
                    value={rule.compare_params?.[pk] ?? pv.default}
                    onChange={(e) =>
                      handleParamChange(pk, e.target.value, "right")
                    }
                  />
                </div>
              ))}
            </div>
          )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Label (auto-generated preview) */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">标签:</span>
          <span className="text-xs font-mono text-foreground/80 max-w-[200px] truncate">
            {rule.label || autoLabel(rule, groups)}
          </span>
        </div>
      </div>
    </div>
  );
}
