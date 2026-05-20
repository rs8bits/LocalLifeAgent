export interface ToolLog {
  tool: string;
  status: string;
  message: string;
}

export interface TimelineItem {
  time: string;
  type: string;
  title: string;
  poi_id: string;
  duration_min: number;
}

export interface Plan {
  plan_id: string;
  title: string;
  scene: string;
  timeline: TimelineItem[];
  activity: Record<string, unknown> | null;
  restaurant: Record<string, unknown> | null;
  drink?: Record<string, unknown> | null;
  route: Record<string, unknown> | null;
  deals: Record<string, unknown>[];
  budget: { total: number; per_person: number; currency: string };
  queue_minutes: number;
  booking_status: string;
  risk_tips: string[];
  recommend_reasons: string[];
  score: number;
  score_reasons: string[];
}

export interface PlanResponse {
  session_id: string;
  user_id: string;
  message: string;
  intent: Record<string, unknown>;
  plans: Plan[];
  tool_logs: ToolLog[];
  errors: string[];
}

export interface BookingResult {
  type: string;
  poi_name: string;
  success: boolean;
  booking_id?: string;
  message: string;
  skipped?: boolean;
}

export interface OrderResult {
  order_id: string;
  deal_title: string;
  success: boolean;
}

export interface ConfirmResponse {
  status: string;
  session_id: string;
  plan_id: string;
  selected_plan: Plan | null;
  execution_result: Record<string, unknown>;
  bookings: BookingResult[];
  orders: OrderResult[];
  share_message: string | null;
  errors: string[];
}
