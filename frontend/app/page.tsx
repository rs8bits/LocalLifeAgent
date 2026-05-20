"use client";

import { useState } from "react";
import type { PlanResponse, ConfirmResponse, Plan } from "@/types/agent";
import { planTrip, confirmPlan } from "@/lib/api";
import ToolLogList from "@/components/ToolLogList";
import PlanCard from "@/components/PlanCard";
import ExecutionResult from "@/components/ExecutionResult";

const FAMILY_EXAMPLE = "今天下午想和老婆孩子出去玩几个小时，别太远，孩子5岁，老婆最近在减肥";
const FRIENDS_EXAMPLE = "今天下午想和4个朋友出去拍照吃饭，去三里屯附近，最好能喝咖啡";

export default function Home() {
  const [userId, setUserId] = useState("user_001");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<PlanResponse | null>(null);
  const [confirmResult, setConfirmResult] = useState<ConfirmResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handlePlan = async () => {
    if (!message.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setConfirmResult(null);
    try {
      const data = await planTrip(userId, message);
      setResult(data);
      if (data.errors && data.errors.length > 0) {
        setError(data.errors.join("; "));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (planId: string) => {
    if (!result?.session_id) return;
    setConfirming(true);
    setError(null);
    try {
      const data = await confirmPlan(result.session_id, planId);
      setConfirmResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "确认请求失败");
    } finally {
      setConfirming(false);
    }
  };

  const handleCopy = () => {
    if (confirmResult?.share_message) {
      navigator.clipboard.writeText(confirmResult.share_message).catch(() => {});
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <main className="max-w-3xl mx-auto p-4 space-y-6">
      <h1 className="text-xl font-bold text-center">LocalLife Agent</h1>
      <p className="text-center text-gray-500 text-sm">
        本地短时活动规划与执行 Demo
      </p>

      {/* 输入区 */}
      <section className="bg-white rounded-lg p-4 shadow-sm space-y-3">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium w-16">用户 ID:</label>
          <input
            type="text"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="border rounded px-2 py-1 text-sm w-32"
          />
        </div>
        <div>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="输入你的需求，例如：今天下午想和老婆孩子出去玩..."
            rows={3}
            className="w-full border rounded px-3 py-2 text-sm resize-none"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={handlePlan}
            disabled={loading || !message.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-sm"
          >
            {loading ? "规划中..." : "开始规划"}
          </button>
          <button
            onClick={() => setMessage(FAMILY_EXAMPLE)}
            className="px-3 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200"
          >
            家庭场景示例
          </button>
          <button
            onClick={() => {
              setMessage(FRIENDS_EXAMPLE);
              setUserId("user_002");
            }}
            className="px-3 py-1 text-xs bg-purple-100 text-purple-700 rounded hover:bg-purple-200"
          >
            朋友场景示例
          </button>
        </div>
      </section>

      {/* 错误 */}
      {error && (
        <section className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">
          {error}
        </section>
      )}

      {/* 工具日志 */}
      {result && (
        <section className="bg-white rounded-lg p-4 shadow-sm">
          <ToolLogList logs={result.tool_logs} />
        </section>
      )}

      {/* 方案区 */}
      {result && result.plans.length > 0 && (
        <section className="space-y-3">
          <h2 className="font-semibold text-base">
            候选方案 ({result.plans.length})
          </h2>
          {result.plans.map((plan: Plan) => (
            <PlanCard
              key={plan.plan_id}
              plan={plan}
              onConfirm={handleConfirm}
              disabled={confirming || !!confirmResult}
            />
          ))}
        </section>
      )}

      {/* 空状态 */}
      {result && result.plans.length === 0 && (
        <section className="text-center text-gray-400 py-8">
          暂未生成候选方案，请尝试调整输入
        </section>
      )}

      {/* 执行结果 */}
      {confirmResult && (
        <section>
          <ExecutionResult
            bookings={confirmResult.bookings}
            orders={confirmResult.orders}
            shareMessage={confirmResult.share_message}
            onCopy={handleCopy}
            copied={copied}
          />
        </section>
      )}
    </main>
  );
}
