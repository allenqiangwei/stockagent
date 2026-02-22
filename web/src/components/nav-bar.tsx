"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  LayoutDashboard,
  LineChart,
  TrendingUp,
  Zap,
  Newspaper,
  FlaskConical,
  Settings2,
  Wrench,
  BrainCircuit,
  Menu,
  Sparkles,
  Flame,
} from "lucide-react";

const navItems = [
  { href: "/", label: "仪表盘", icon: LayoutDashboard },
  { href: "/market", label: "行情", icon: LineChart },
  { href: "/market-overview", label: "大盘", icon: TrendingUp },
  { href: "/signals", label: "信号", icon: Zap },
  { href: "/sectors", label: "板块", icon: Flame },
  { href: "/news", label: "资讯", icon: Newspaper },
  { href: "/backtest", label: "回测", icon: FlaskConical },
  { href: "/lab", label: "实验室", icon: BrainCircuit },
  { href: "/ai", label: "AI分析", icon: Sparkles },
  { href: "/strategies", label: "策略管理", icon: Settings2 },
  { href: "/settings", label: "设置", icon: Wrench },
];

export function NavBar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-sm">
      <div className="flex h-12 items-center px-3 sm:px-4 gap-3 sm:gap-6">
        {/* Hamburger — visible below lg */}
        <button
          onClick={() => setOpen(true)}
          className="lg:hidden flex items-center justify-center rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          aria-label="打开导航菜单"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 font-semibold text-sm tracking-tight">
          <LineChart className="h-5 w-5 text-chart-1" />
          <span className="hidden sm:inline">StockAgent</span>
        </Link>

        {/* Desktop nav — hidden below lg */}
        <nav className="hidden lg:flex items-center gap-1">
          {navItems.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Mobile: show current page name on right */}
        <span className="lg:hidden ml-auto text-xs text-muted-foreground truncate">
          {navItems.find((n) =>
            n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)
          )?.label ?? ""}
        </span>
      </div>

      {/* Mobile drawer */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetHeader className="px-4 py-3 border-b border-border/40">
            <SheetTitle className="flex items-center gap-2 text-sm">
              <LineChart className="h-5 w-5 text-chart-1" />
              StockAgent
            </SheetTitle>
          </SheetHeader>
          <nav className="flex flex-col py-2">
            {navItems.map(({ href, label, icon: Icon }) => {
              const active =
                href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-4 py-2.5 text-sm transition-colors",
                    active
                      ? "bg-accent text-accent-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              );
            })}
          </nav>
        </SheetContent>
      </Sheet>
    </header>
  );
}
