import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      className={cn(
        "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
        active
          ? "border-blue-600 text-blue-700"
          : "border-transparent text-gray-500 hover:text-gray-700",
      )}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}
