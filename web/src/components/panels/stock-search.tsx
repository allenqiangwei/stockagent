"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { useStockSearch, useAddWatchlist } from "@/hooks/use-queries";
import { useAppStore } from "@/lib/store";
import { Search, Plus } from "lucide-react";

export function StockSearch() {
  const [keyword, setKeyword] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const setCurrentStock = useAppStore((s) => s.setCurrentStock);
  const { data } = useStockSearch(keyword);
  const addWatchlist = useAddWatchlist();

  const selectFirst = useCallback(() => {
    const first = data?.items?.[0];
    if (first) {
      setCurrentStock(first.code, first.name);
      setKeyword("");
      inputRef.current?.blur();
    }
  }, [data, setCurrentStock]);

  // Global keyboard shortcut: type digits anywhere to search stocks
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const isInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

      // Digits 0-9: auto-focus search (only when no input is focused)
      if (/^[0-9]$/.test(e.key) && !isInput) {
        e.preventDefault();
        setKeyword(e.key);
        // Focus after state update via microtask
        queueMicrotask(() => {
          const el = inputRef.current;
          if (el) {
            el.focus();
            // Place cursor after the digit
            el.setSelectionRange(1, 1);
          }
        });
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      selectFirst();
    } else if (e.key === "Escape") {
      setKeyword("");
      inputRef.current?.blur();
    }
  };

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
        <Input
          ref={inputRef}
          placeholder="搜索股票代码或名称"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={handleKeyDown}
          className="pl-8 h-8 text-sm"
        />
      </div>
      {data?.items && keyword && (
        <div className="max-h-48 overflow-y-auto space-y-0.5">
          {data.items.map((s, i) => (
            <div
              key={s.code}
              className={`flex items-center justify-between rounded px-2 py-1 text-sm cursor-pointer ${
                i === 0 ? "bg-accent/50" : "hover:bg-accent/50"
              }`}
              onClick={() => {
                setCurrentStock(s.code, s.name);
                setKeyword("");
              }}
            >
              <div>
                <span className="font-mono text-xs">{s.code}</span>{" "}
                <span className="text-muted-foreground">{s.name}</span>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  addWatchlist.mutate({ code: s.code, name: s.name });
                }}
                className="text-muted-foreground hover:text-foreground"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
