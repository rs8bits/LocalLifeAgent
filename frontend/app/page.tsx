"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { PlanResponse, ConfirmResponse, Plan } from "@/types/agent";
import {
  planTrip,
  confirmPlan,
  revisePlan,
  planTripStream,
  revisePlanStream,
  confirmPlanStream,
} from "@/lib/api";
import ToolLogList from "@/components/ToolLogList";
import PlanCard from "@/components/PlanCard";
import ExecutionResult from "@/components/ExecutionResult";
import AmapPanel, { type MapPoi } from "@/components/AmapPanel";

const FAMILY_EXAMPLE = "今天下午想和老婆孩子出去玩几个小时，别太远，孩子5岁，老婆最近在减肥";
const FRIENDS_EXAMPLE = "今天下午想和4个朋友出去拍照吃饭，去三里屯附近，最好能喝咖啡";

interface StreamLogItem {
  event: string;
  message: string;
  time: string;
  phase: "首次规划" | "继续修改" | "确认执行";
}

function recordToMapPoi(poi: Record<string, unknown>): MapPoi | null {
  const id = stringValue(poi.id) ?? stringValue(poi.poi_id) ?? stringValue(poi.name);
  const name = stringValue(poi.name) ?? stringValue(poi.merchant_name);
  const lat = typeof poi.lat === "number" ? poi.lat : Number(poi.lat);
  const lng = typeof poi.lng === "number" ? poi.lng : Number(poi.lng);
  if (!id || !name || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return {
    id,
    name,
    lat,
    lng,
    address: stringValue(poi.address),
    category: stringValue(poi.category),
    image_url: stringValue(poi.image_url),
  };
}

function collectPlanPois(plans: Plan[]): MapPoi[] {
  const byId = new Map<string, MapPoi>();
  for (const plan of plans) {
    const records: Record<string, unknown>[] = [];
    if (plan.activity) records.push(plan.activity);
    records.push(...((plan.extra_activities ?? []) as Record<string, unknown>[]));
    if (plan.restaurant) records.push(plan.restaurant);
    records.push(...(plan.meal_restaurants ?? []).map((entry) => entry.restaurant));
    if (plan.drink) records.push(plan.drink);
    records.push(...((plan.delivery_items ?? []) as Record<string, unknown>[]));

    for (const record of records) {
      const poi = recordToMapPoi(record);
      if (poi && !byId.has(poi.id)) byId.set(poi.id, poi);
    }
  }
  return Array.from(byId.values());
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export default function Home() {
  const [userId, setUserId] = useState("user_001");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [revising, setRevising] = useState(false);
  const [result, setResult] = useState<PlanResponse | null>(null);
  const [confirmResult, setConfirmResult] = useState<ConfirmResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [revisionMessage, setRevisionMessage] = useState("");
  const [selectedRevisionPlanId, setSelectedRevisionPlanId] = useState<string | null>(null);
  const [selectedPoi, setSelectedPoi] = useState<MapPoi | null>(null);

  // 流式过程日志
  const [streamLogs, setStreamLogs] = useState<StreamLogItem[]>([]);

  const addStreamLog = (
    event: string,
    message: string,
    phase: StreamLogItem["phase"] = "首次规划"
  ) => {
    setStreamLogs((prev) => [
      ...prev,
      { event, message, phase, time: new Date().toLocaleTimeString() },
    ]);
  };

  useEffect(() => {
    if (!result?.plans.length) {
      setSelectedRevisionPlanId(null);
      return;
    }
    setSelectedRevisionPlanId((current) => {
      if (current && result.plans.some((plan) => plan.plan_id === current)) {
        return current;
      }
      return result.plans[0].plan_id;
    });
  }, [result?.session_id, result?.plans]);

  const mapPois = useMemo(() => collectPlanPois(result?.plans ?? []), [result?.plans]);

  useEffect(() => {
    if (mapPois.length === 0) {
      setSelectedPoi(null);
      return;
    }
    setSelectedPoi((current) => {
      if (current && mapPois.some((poi) => poi.id === current.id)) {
        return current;
      }
      return mapPois[0];
    });
  }, [mapPois]);

  const handlePoiSelect = useCallback((poi: MapPoi) => {
    setSelectedPoi(poi);
  }, []);

  const handlePlan = async () => {
    if (!message.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setConfirmResult(null);
    setSelectedRevisionPlanId(null);
    setSelectedPoi(null);
    setStreamLogs([]);
    addStreamLog("plan_request", `首次需求：${message}`, "首次规划");

    try {
      let streamFinalResult: PlanResponse | null = null;
      // 优先使用流式接口
      await planTripStream(userId, message, (event) => {
        const evtType = event.event as string || "unknown";
        const msg = event.message as string || "";
        addStreamLog(evtType, msg || "正在处理首次规划流程", "首次规划");

        // 处理 plan_delta / plan_done 事件
        if (evtType === "plan_delta" && event.data) {
          const data = event.data as Record<string, unknown>;
          const plan = data.plan as Plan | undefined;
          if (plan) {
            setResult((prev) => {
              if (!prev) {
                const newResult: PlanResponse = {
                  session_id: "",
                  user_id: userId,
                  message: message,
                  intent: {},
                  plans: [plan],
                  tool_logs: [],
                  errors: [],
                };
                return newResult;
              }
              const existingIds = new Set(prev.plans.map((p) => p.plan_id));
              if (!existingIds.has(plan.plan_id)) {
                return { ...prev, plans: [...prev.plans, plan] };
              }
              return prev;
            });
          }
        }

        if (evtType === "tool_done" && event.data) {
          const data = event.data as Record<string, unknown>;
          setResult((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              tool_logs: [
                ...prev.tool_logs,
                {
                  tool: (data.tool as string) || "",
                  status: (data.status as string) || "ok",
                  message: msg,
                },
              ],
            };
          });
        }

        if (evtType === "plan_done" && event.data) {
          const data = event.data as Record<string, unknown>;
          const finalResult = data.result as PlanResponse | undefined;
          if (finalResult?.session_id) {
            streamFinalResult = finalResult;
            setResult(finalResult);
            if (finalResult.errors && finalResult.errors.length > 0) {
              setError(finalResult.errors.join("; "));
            }
          }
        }
      });

      if (!streamFinalResult) {
        const fullResult = await planTrip(userId, message);
        setResult(fullResult);
        if (fullResult.errors && fullResult.errors.length > 0) {
          setError(fullResult.errors.join("; "));
        }
      }
    } catch (e) {
      // fallback 到非流式
      addStreamLog("error", "流式接口失败，切换到普通模式", "首次规划");
      try {
        const data = await planTrip(userId, message);
        setResult(data);
        if (data.errors && data.errors.length > 0) {
          setError(data.errors.join("; "));
        }
      } catch (e2) {
        setError(e2 instanceof Error ? e2.message : "请求失败");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (planId: string) => {
    if (!result?.session_id) return;
    setConfirming(true);
    setError(null);

    try {
      let streamConfirmResult: ConfirmResponse | null = null;
      // 使用流式确认接口
      await confirmPlanStream(result.session_id, planId, (event) => {
        const evtType = event.event as string || "unknown";
        const msg = event.message as string || "";
        addStreamLog(evtType, msg || "正在执行确认流程", "确认执行");

        if (evtType === "confirm_done" && event.data) {
          const data = event.data as Record<string, unknown>;
          const finalResult = data.result as ConfirmResponse | undefined;
          if (finalResult?.session_id) {
            streamConfirmResult = finalResult;
            setConfirmResult(finalResult);
          }
        }
      });

      if (!streamConfirmResult) {
        const fullResult = await confirmPlan(result.session_id, planId);
        setConfirmResult(fullResult);
      }
    } catch (e) {
      // fallback to non-streaming
      addStreamLog("error", "流式确认失败，切换到普通模式", "确认执行");
      try {
        const data = await confirmPlan(result.session_id, planId);
        setConfirmResult(data);
      } catch (e2) {
        setError(e2 instanceof Error ? e2.message : "确认请求失败");
      }
    } finally {
      setConfirming(false);
    }
  };

  const handleRevise = async () => {
    if (!result?.session_id || !revisionMessage.trim()) return;
    const sourceSessionId = result.session_id;
    const basePlanId = selectedRevisionPlanId ?? result.plans[0]?.plan_id;
    const currentRevisionMessage = revisionMessage;
    setRevising(true);
    setError(null);
    setConfirmResult(null);
    setSelectedPoi(null);
    setResult((prev) => prev ? { ...prev, plans: [], tool_logs: [], errors: [] } : prev);
    addStreamLog("revision_request", `修改需求：${currentRevisionMessage}`, "继续修改");
    addStreamLog("revision_start", "正在根据修改建议重新规划...", "继续修改");

    try {
      let streamFinalResult: PlanResponse | null = null;
      await revisePlanStream(sourceSessionId, currentRevisionMessage, basePlanId, (event) => {
        const evtType = event.event as string || "unknown";
        const msg = event.message as string || "";
        addStreamLog(evtType, msg || "正在处理修改规划流程", "继续修改");

        if (evtType === "plan_delta" && event.data) {
          const data = event.data as Record<string, unknown>;
          const plan = data.plan as Plan | undefined;
          if (plan) {
            setResult((prev) => {
              if (!prev) {
                return {
                  session_id: "",
                  user_id: userId,
                  message: currentRevisionMessage,
                  intent: {},
                  plans: [plan],
                  tool_logs: [],
                  errors: [],
                };
              }
              const existingIds = new Set(prev.plans.map((p) => p.plan_id));
              if (!existingIds.has(plan.plan_id)) {
                return { ...prev, plans: [...prev.plans, plan] };
              }
              return prev;
            });
          }
        }

        if (evtType === "tool_done" && event.data) {
          const data = event.data as Record<string, unknown>;
          setResult((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              tool_logs: [
                ...prev.tool_logs,
                {
                  tool: (data.tool as string) || "",
                  status: (data.status as string) || "ok",
                  message: msg,
                },
              ],
            };
          });
        }

        if (evtType === "plan_done" && event.data) {
          const data = event.data as Record<string, unknown>;
          const finalResult = data.result as PlanResponse | undefined;
          if (finalResult?.session_id) {
            streamFinalResult = finalResult;
            setResult(finalResult);
            setRevisionMessage("");
            addStreamLog("revision_done", `修改完成，生成 ${finalResult.plans.length} 个候选方案`, "继续修改");
            if (finalResult.errors && finalResult.errors.length > 0) {
              setError(finalResult.errors.join("; "));
            }
          }
        }
      });

      if (!streamFinalResult) {
        const revised = await revisePlan(sourceSessionId, currentRevisionMessage, basePlanId);
        setResult(revised);
        setRevisionMessage("");
        addStreamLog("revision_done", `修改完成，生成 ${revised.plans.length} 个候选方案`, "继续修改");
        if (revised.errors && revised.errors.length > 0) {
          setError(revised.errors.join("; "));
        }
      }
    } catch (e) {
      addStreamLog("revision_error", "流式修改失败，切换到普通模式", "继续修改");
      try {
        const revised = await revisePlan(sourceSessionId, currentRevisionMessage, basePlanId);
        setResult(revised);
        setRevisionMessage("");
        addStreamLog("revision_done", `修改完成，生成 ${revised.plans.length} 个候选方案`, "继续修改");
        if (revised.errors && revised.errors.length > 0) {
          setError(revised.errors.join("; "));
        }
      } catch (e2) {
        setError(e2 instanceof Error ? e2.message : "修改规划失败");
        addStreamLog("revision_error", "修改规划失败", "继续修改");
      }
    } finally {
      setRevising(false);
    }
  };

  const handleCopy = () => {
    if (confirmResult?.share_message) {
      navigator.clipboard.writeText(confirmResult.share_message).catch(() => {});
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const intentPartyType = result?.intent?.party_type as string | undefined;
  const intentTags = Array.isArray(result?.intent?.tags)
    ? (result?.intent?.tags as unknown[]).filter((tag): tag is string => typeof tag === "string")
    : [];
  const intentDomains = Array.isArray(result?.intent?.domains)
    ? (result?.intent?.domains as unknown[]).filter((domain): domain is string => typeof domain === "string")
    : [];
  const selectedRevisionPlan = result?.plans.find((plan) => plan.plan_id === selectedRevisionPlanId);
  const intentPeopleCount = typeof result?.intent?.people_count === "number"
    ? result.intent.people_count
    : null;

  return (
    <main className="min-h-screen min-w-[1180px] bg-[#f4f7fb] text-slate-950">
      <header className="h-[72px] border-b border-slate-200 bg-white">
        <div className="flex h-full items-center justify-between px-8">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded bg-blue-600 text-base font-bold text-white">
              LL
            </div>
            <div className="text-3xl font-semibold text-blue-600">LocalLife</div>
          </div>
          <div className="rounded-full bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700">
            AI 行程助手
          </div>
        </div>
      </header>

      <div className="flex h-[64px] items-center border-b border-slate-200 bg-white px-6">
        <h1 className="truncate text-2xl font-semibold">
          {result?.plans[0]?.title ?? "AI 本地行程规划"}
        </h1>
      </div>

      <section className="grid h-[calc(100vh-136px)] grid-cols-[360px_minmax(420px,1fr)_minmax(420px,1fr)] overflow-hidden">
        <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-[#f7f9fd]">
          <div className="flex h-[70px] items-center justify-between px-6">
            <div className="flex items-center gap-2 text-xl font-semibold">
              <span>✦</span>
              <span>AI助手</span>
            </div>
          </div>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 pb-24">
            <section className="rounded-lg bg-[#eaf1ff] p-4">
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="我想去厦门旅行，从南昌出发。出行时间是8月，玩3天。请帮我设计出行的详细行程。"
                rows={4}
                className="w-full resize-none bg-transparent text-base leading-7 outline-none placeholder:text-slate-500"
              />
              <div className="mt-3 flex items-center gap-2">
                <span className="text-xs text-slate-500">用户 ID</span>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  className="h-8 w-28 rounded border border-blue-100 bg-white px-2 text-xs outline-none focus:border-blue-400"
                />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setMessage(FAMILY_EXAMPLE)}
                  className="rounded border border-blue-100 bg-white px-3 py-1.5 text-xs text-blue-700"
                >
                  家庭场景
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMessage(FRIENDS_EXAMPLE);
                    setUserId("user_002");
                  }}
                  className="rounded border border-blue-100 bg-white px-3 py-1.5 text-xs text-blue-700"
                >
                  朋友场景
                </button>
                <button
                  type="button"
                  onClick={handlePlan}
                  disabled={loading || !message.trim()}
                  className="ml-auto rounded bg-blue-600 px-4 py-1.5 text-xs font-semibold text-white disabled:bg-slate-300"
                >
                  {loading ? "规划中" : "发送"}
                </button>
              </div>
            </section>

            {error && (
              <section className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {error}
              </section>
            )}

            {result?.session_id && (
              <section className="rounded-lg bg-white p-4 shadow-sm">
                <h3 className="text-base font-semibold">继续修改方案</h3>
                {selectedRevisionPlan && (
                  <div className="mt-3 rounded bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-700">
                    正在修改：{selectedRevisionPlan.title}
                  </div>
                )}
                <textarea
                  value={revisionMessage}
                  onChange={(e) => setRevisionMessage(e.target.value)}
                  placeholder="给这个方案加中饭；只替换晚餐；不要动活动，晚上想喝酒"
                  rows={3}
                  className="mt-3 w-full resize-none rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 outline-none focus:border-blue-500 focus:bg-white"
                />
                <button
                  type="button"
                  onClick={handleRevise}
                  disabled={revising || !revisionMessage.trim()}
                  className="mt-3 h-10 w-full rounded bg-blue-600 text-sm font-semibold text-white disabled:bg-slate-300"
                >
                  {revising ? "修改中..." : "重新规划"}
                </button>
              </section>
            )}

            {streamLogs.length > 0 && (
              <section className="rounded-lg bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center justify-between text-sm">
                  <span className="font-semibold">
                    {loading || revising ? "深度思考中" : "深度思考已完成"}
                  </span>
                  <span className="text-slate-500">{streamLogs.length} 条</span>
                </div>
                <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
                  {streamLogs.map((log, i) => (
                    <div
                      key={i}
                      className={`rounded border px-3 py-2 text-xs ${
                        log.phase === "继续修改"
                          ? "border-indigo-100 bg-indigo-50"
                          : log.phase === "确认执行"
                          ? "border-emerald-100 bg-emerald-50"
                          : "border-blue-100 bg-blue-50"
                      }`}
                    >
                      <div className="mb-1 flex items-center justify-between">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={`shrink-0 rounded px-1.5 py-0.5 font-medium ${
                              log.phase === "继续修改"
                                ? "bg-indigo-600 text-white"
                                : log.phase === "确认执行"
                                ? "bg-emerald-600 text-white"
                                : "bg-blue-600 text-white"
                            }`}
                          >
                            {log.phase}
                          </span>
                          <span className="truncate font-mono text-slate-600">{log.event}</span>
                        </div>
                        <span className="font-mono text-slate-400">{log.time}</span>
                      </div>
                      <p className="leading-5 text-slate-600">{log.message}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {result && (
              <section className="rounded-lg bg-white p-4 shadow-sm">
                <ToolLogList logs={result.tool_logs} />
              </section>
            )}
          </div>
        </aside>

        <section className="min-h-0 overflow-y-auto border-r border-slate-200 bg-white">
          <div className="sticky top-0 z-10 border-b border-slate-200 bg-white px-6 pt-5">
            <h2 className="border-b-2 border-slate-950 pb-4 text-xl font-semibold">
              行程详情
            </h2>
          </div>

          <div className="space-y-5 p-6">
            {result && (
              <section className="rounded-lg border border-slate-200 bg-white p-4">
                <h3 className="text-lg font-semibold">意图摘要</h3>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  {intentPartyType && (
                    <span className="rounded bg-blue-50 px-2 py-1 text-blue-700">
                      party_type={intentPartyType}
                    </span>
                  )}
                  {intentTags.map((tag) => (
                    <span key={tag} className="rounded bg-slate-100 px-2 py-1 text-slate-700">
                      {tag}
                    </span>
                  ))}
                  {intentDomains.map((domain) => (
                    <span key={domain} className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">
                      domain={domain}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {result && result.plans.length > 0 && (
              <section className="space-y-4">
                <h2 className="text-2xl font-semibold">候选方案 ({result.plans.length})</h2>
                {result.plans.map((plan: Plan) => (
                  <PlanCard
                    key={plan.plan_id}
                  plan={plan}
                  peopleCount={intentPeopleCount}
                  onConfirm={handleConfirm}
                  onSelectForRevision={setSelectedRevisionPlanId}
                  onPoiSelect={handlePoiSelect}
                  selectedPoiId={selectedPoi?.id ?? null}
                  isRevisionBase={selectedRevisionPlanId === plan.plan_id}
                  disabled={confirming || !!confirmResult}
                />
                ))}
              </section>
            )}

            {result && result.plans.length === 0 && (
              <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-400">
                暂未生成候选方案，请尝试调整输入
              </section>
            )}

            {!result && !loading && (
              <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
                在左侧输入需求后，这里会展示真实生成的候选方案。
              </section>
            )}

            {loading && (
              <section className="rounded-lg border border-blue-100 bg-blue-50 p-10 text-center text-sm text-blue-700">
                正在生成方案...
              </section>
            )}
          </div>
        </section>

        <aside className="min-h-0 overflow-y-auto bg-[#eef5ff] p-5">
          <div className="flex min-h-full flex-col gap-5">
            <AmapPanel
              pois={mapPois}
              selectedPoi={selectedPoi}
              onPoiSelect={handlePoiSelect}
            />
            {confirmResult && (
              <div>
                <ExecutionResult
                  bookings={confirmResult.bookings}
                  orders={confirmResult.orders}
                  shareMessage={confirmResult.share_message}
                  onCopy={handleCopy}
                  copied={copied}
                />
              </div>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}
