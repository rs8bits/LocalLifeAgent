"use client";

import type { Plan } from "@/types/agent";

export default function PlanCard({
  plan,
  onConfirm,
  disabled,
}: {
  plan: Plan;
  onConfirm: (planId: string) => void;
  disabled: boolean;
}) {
  const activity = plan.activity;
  const restaurant = plan.restaurant;
  const drink = plan.drink;
  const deliveryItems = plan.delivery_items ?? [];
  const route = plan.route;

  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm flex flex-col gap-3">
      {/* 标题 */}
      <div className="flex justify-between items-start">
        <div>
          <h3 className="font-semibold text-base">{plan.title}</h3>
        </div>
        <span
          className={`text-xs px-2 py-0.5 rounded ${
            plan.booking_status === "available"
              ? "bg-green-100 text-green-700"
              : plan.booking_status === "partial"
              ? "bg-yellow-100 text-yellow-700"
              : "bg-red-100 text-red-700"
          }`}
        >
          {plan.booking_status === "available"
            ? "可预约"
            : plan.booking_status === "partial"
            ? "部分可约"
            : "不可预约"}
        </span>
      </div>

      {/* 时间线 */}
      {plan.timeline.length > 0 && (
        <div className="text-sm space-y-0.5">
          {plan.timeline.map((t, i) => {
            const isTransit = t.type === "transit";
            const isDrink = t.type === "drink";
            const isDelivery = t.type === "delivery";
            return (
              <div key={i} className={`flex items-center gap-2 ${isTransit ? "text-gray-400 text-xs" : ""}`}>
                <span className="font-mono text-xs w-12 shrink-0">{t.time}</span>
                <span className={isDelivery ? "text-cyan-700 font-medium" : isDrink ? "text-purple-600 font-medium" : isTransit ? "" : "font-medium"}>
                  {isTransit ? "🚶 " : isDelivery ? "配送 " : isDrink ? "🥤 " : "📍 "}
                  {t.title}
                </span>
                <span className="text-gray-400 text-xs">{t.duration_min}min</span>
              </div>
            );
          })}
        </div>
      )}

      {/* 外卖/闪送 */}
      {deliveryItems.length > 0 && (
        <div className="text-sm">
          <span className="text-gray-500">外卖/闪送: </span>
          <span className="font-medium text-cyan-700">
            {deliveryItems.map((item) => item.name as string).join(", ")}
          </span>
        </div>
      )}

      {/* 活动 */}
      {activity && (
        <div className="text-sm">
          <span className="text-gray-500">活动: </span>
          <span className="font-medium">{activity.name as string}</span>
          <span className="text-gray-400 ml-2">
            {(activity.avg_price as number) ?? 0}元/人
          </span>
          {(activity.indoor as boolean) && (
            <span className="text-blue-600 text-xs ml-1">室内</span>
          )}
        </div>
      )}

      {/* 饮品 */}
      {drink && (
        <div className="text-sm">
          <span className="text-gray-500">饮品: </span>
          <span className="font-medium text-purple-600">{drink.name as string}</span>
          <span className="text-gray-400 ml-2">
            {(drink.avg_price as number) ?? 0}元/人
          </span>
        </div>
      )}

      {/* 餐厅 */}
      {restaurant && (
        <div className="text-sm">
          <span className="text-gray-500">餐厅: </span>
          <span className="font-medium">{restaurant.name as string}</span>
          <span className="text-gray-400 ml-2">
            {(restaurant.avg_price as number) ?? 0}元/人
          </span>
          {(restaurant.queue_minutes as number) > 0 && (
            <span className="text-orange-500 text-xs ml-1">
              排队约{(restaurant.queue_minutes as number)}分钟
            </span>
          )}
        </div>
      )}

      {/* 路线 */}
      {route && (
        <div className="text-sm text-gray-500">
          路线: {(route.transport as string)} · {(route.duration_min as number)}分钟
        </div>
      )}

      {/* 预算 */}
      <div className="text-sm">
        <span className="text-gray-500">预算: </span>
        <span className="font-semibold">
          ￥{plan.budget?.per_person ?? 0}/人 (共￥{plan.budget?.total ?? 0})
        </span>
      </div>

      {/* 风险提示 */}
      {plan.risk_tips.length > 0 && (
        <div className="text-xs bg-orange-50 p-2 rounded">
          {plan.risk_tips.map((tip, i) => (
            <p key={i} className="text-orange-700">
              ⚠ {tip}
            </p>
          ))}
        </div>
      )}

      {/* 推荐理由 */}
      {plan.recommend_reasons.length > 0 && (
        <div className="text-xs text-green-700 flex flex-wrap gap-1">
          {plan.recommend_reasons.map((r, i) => (
            <span key={i} className="bg-green-50 px-1.5 py-0.5 rounded">
              {r}
            </span>
          ))}
        </div>
      )}

      {/* 团购券 */}
      {plan.deals.length > 0 && (
        <div className="text-xs text-gray-600">
          团购券:{" "}
          {plan.deals.map((d) => (d as Record<string, unknown>).title as string).join(", ")}
        </div>
      )}

      {/* 确认按钮 */}
      <button
        onClick={() => onConfirm(plan.plan_id)}
        disabled={disabled}
        className="mt-1 w-full py-2 bg-blue-600 text-white rounded font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-sm"
      >
        确认并安排
      </button>
    </div>
  );
}
