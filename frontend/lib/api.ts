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

// ═══ 流式 API ═══

export type StreamEventCallback = (event: Record<string, unknown>) => void;

export async function planTripStream(
  userId: string,
  message: string,
  onEvent: StreamEventCallback
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/agent/plan/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, message }),
  });

  if (!resp.ok) {
    throw new Error(`请求失败 (${resp.status}): ${await resp.text()}`);
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error("不支持流式读取");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent(data);
        } catch {
          // 跳过解析失败的行
        }
      }
    }
  }
}

export async function confirmPlanStream(
  sessionId: string,
  planId: string,
  onEvent: StreamEventCallback
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/agent/confirm/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, plan_id: planId }),
  });

  if (!resp.ok) {
    throw new Error(`请求失败 (${resp.status}): ${await resp.text()}`);
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error("不支持流式读取");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent(data);
        } catch {
          // skip
        }
      }
    }
  }
}
