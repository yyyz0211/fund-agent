import { ShieldCheck } from "lucide-react";

export function Disclaimer() {
  return (
    <div className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-2 text-xs text-gray-600 sm:px-6">
        <ShieldCheck className="h-3.5 w-3.5 text-blue-600" />
        <p>本工具仅整理公开信息与历史数据，不构成投资建议。所有数字来自公开数据源，标注的 source/as_of 即为数据出处与日期。</p>
      </div>
    </div>
  );
}
