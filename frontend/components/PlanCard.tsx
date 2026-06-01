"use client";

import type { Plan } from "@/types/agent";

export default function PlanCard({
  plan,
  peopleCount,
  onConfirm,
  onSelectForRevision,
  disabled,
  isRevisionBase = false,
}: {
  plan: Plan;
  peopleCount?: number | null;
  onConfirm: (planId: string) => void;
  onSelectForRevision?: (planId: string) => void;
  disabled: boolean;
  isRevisionBase?: boolean;
}) {
  const activity = plan.activity;
  const restaurant = plan.restaurant;
  const mealRestaurants = plan.meal_restaurants ?? [];
  const drink = plan.drink;
  const deliveryItems = plan.delivery_items ?? [];
  const route = plan.route;

  return (
    <div
      className={`border rounded-lg p-4 bg-white shadow-sm flex flex-col gap-3 ${
        isRevisionBase ? "border-indigo-500 ring-2 ring-indigo-100" : "border-gray-200"
      }`}
    >
      {/* 标题 */}
      <div className="flex justify-between items-start">
        <div>
          <h3 className="font-semibold text-base">{plan.title}</h3>
          <div className="flex flex-wrap gap-1 mt-1">
            {plan.party_type && (
              <span className="text-xs bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">
                {plan.party_type}
              </span>
            )}
            {typeof peopleCount === "number" && peopleCount > 0 && (
              <span className="text-xs bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded">
                {peopleCount}人
              </span>
            )}
            {typeof plan.score === "number" && plan.score > 0 && (
              <span className="text-xs text-blue-700">
                推荐分 {(plan.score * 100).toFixed(0)}
              </span>
            )}
          </div>
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
      {mealRestaurants.length > 0 ? (
        <div className="text-sm space-y-1">
          {mealRestaurants.map((entry, index) => {
            const item = entry.restaurant;
            return (
              <div key={`${entry.meal}-${(item.id as string) ?? index}`}>
                <span className="text-gray-500">{entry.label ?? entry.meal}: </span>
                <span className="font-medium">{item.name as string}</span>
                <span className="text-gray-400 ml-2">
                  {(item.avg_price as number) ?? 0}元/人
                </span>
                {(item.category as string) && (
                  <span className="text-gray-500 text-xs ml-1">
                    {(item.category as string)}
                  </span>
                )}
                {(item.queue_minutes as number) > 0 && (
                  <span className="text-orange-500 text-xs ml-1">
                    排队约{(item.queue_minutes as number)}分钟
                  </span>
                )}
              </div>
            );
          })}
        </div>
      ) : restaurant && (
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

      {/* 评分理由 */}
      {plan.score_reasons.length > 0 && (
        <div className="text-xs text-blue-700 bg-blue-50 p-2 rounded space-y-0.5">
          {plan.score_reasons.slice(0, 3).map((reason, i) => (
            <p key={i}>{reason}</p>
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

      {/* 操作按钮 */}
      <div className="mt-1 grid gap-2 sm:grid-cols-2">
        {onSelectForRevision && (
          <button
            type="button"
            onClick={() => onSelectForRevision(plan.plan_id)}
            disabled={disabled}
            className={`w-full py-2 rounded font-medium text-sm border ${
              isRevisionBase
                ? "bg-indigo-50 border-indigo-300 text-indigo-700"
                : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50"
            } disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed`}
          >
            {isRevisionBase ? "当前修改基准" : "以此方案修改"}
          </button>
        )}
        <button
          type="button"
          onClick={() => onConfirm(plan.plan_id)}
          disabled={disabled}
          className="w-full py-2 bg-blue-600 text-white rounded font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-sm"
        >
          确认并安排
        </button>
      </div>
    </div>
  );
}
