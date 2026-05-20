"use client";

import type { ToolLog } from "@/types/agent";

export default function ToolLogList({ logs }: { logs: ToolLog[] }) {
  if (!logs || logs.length === 0) {
    return <p className="text-gray-400 text-sm">暂无工具调用日志</p>;
  }

  return (
    <div className="space-y-1">
      <h3 className="font-semibold text-sm mb-2">工具调用日志</h3>
      {logs.map((log, i) => (
        <div
          key={i}
          className={`text-xs px-2 py-1 rounded flex items-center gap-2 ${
            log.status === "ok" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"
          }`}
        >
          <span className="font-mono font-semibold">{log.tool}</span>
          <span className="text-gray-500">|</span>
          <span>{log.message}</span>
        </div>
      ))}
    </div>
  );
}
