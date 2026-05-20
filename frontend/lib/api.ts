import type { PlanResponse, ConfirmResponse } from "@/types/agent";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function planTrip(
  userId: string,
  message: string
): Promise<PlanResponse> {
  const resp = await fetch(`${API_BASE}/api/agent/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, message }),
  });
  if (!resp.ok) {
    throw new Error(`请求失败 (${resp.status}): ${await resp.text()}`);
  }
  return resp.json();
}

export async function confirmPlan(
  sessionId: string,
  planId: string
): Promise<ConfirmResponse> {
  const resp = await fetch(`${API_BASE}/api/agent/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, plan_id: planId }),
  });
  if (!resp.ok) {
    throw new Error(`请求失败 (${resp.status}): ${await resp.text()}`);
  }
  return resp.json();
}

export async function getSession(sessionId: string): Promise<Record<string, unknown>> {
  const resp = await fetch(`${API_BASE}/api/agent/session/${sessionId}`);
  if (!resp.ok) {
    throw new Error(`请求失败 (${resp.status}): ${await resp.text()}`);
  }
  return resp.json();
}
