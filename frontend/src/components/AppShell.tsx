"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, FileText, Home, MessageSquareText, Star } from "lucide-react";
import { Disclaimer } from "@/components/Disclaimer";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { href: "/", label: "总览", icon: Home },
  { href: "/watchlist", label: "自选池", icon: Star },
  { href: "/announcements", label: "公告", icon: FileText },
  { href: "/qa", label: "问答", icon: MessageSquareText },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-gray-50 text-gray-950">
      <Disclaimer />
      <header className="sticky top-0 z-20 border-b border-gray-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link className="flex items-center gap-3" href="/">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm">
              <BarChart3 className="h-5 w-5" />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold text-gray-950">基金信息助手</span>
              <span className="block text-xs text-gray-500">Fund Agent</span>
            </span>
          </Link>

          <nav className="hidden items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 md:flex">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  className={cn(
                    "inline-flex h-8 items-center gap-2 rounded-md px-3 text-sm font-medium text-gray-600 transition",
                    active ? "bg-white text-blue-700 shadow-sm" : "hover:bg-white hover:text-gray-950",
                  )}
                  href={item.href}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <Link href="/qa">
            <Button size="sm">进入问答</Button>
          </Link>
        </div>
      </header>
      {children}
    </div>
  );
}
