"use client";

import type { Plan } from "@/types/agent";
import type { MapPoi } from "@/components/AmapPanel";

export default function PlanCard({
  plan,
  peopleCount,
  onConfirm,
  onSelectForRevision,
  onPoiSelect,
  selectedPoiId,
  disabled,
  isRevisionBase = false,
}: {
  plan: Plan;
  peopleCount?: number | null;
  onConfirm: (planId: string) => void;
  onSelectForRevision?: (planId: string) => void;
  onPoiSelect?: (poi: MapPoi) => void;
  selectedPoiId?: string | null;
  disabled: boolean;
  isRevisionBase?: boolean;
}) {
  const activity = plan.activity;
  const extraActivities = plan.extra_activities ?? [];
  const activities = [activity, ...extraActivities].filter(Boolean) as Record<string, unknown>[];
  const restaurant = plan.restaurant;
  const mealRestaurants = plan.meal_restaurants ?? [];
  const drink = plan.drink;
  const deliveryItems = plan.delivery_items ?? [];
  const route = plan.route;
  const poiCards: { label: string; poi: Record<string, unknown> }[] = [
    ...activities.map((poi, index) => ({ label: index === 0 ? "活动" : "加场活动", poi })),
    ...mealRestaurants.map((entry) => ({ label: entry.label ?? entry.meal ?? "餐厅", poi: entry.restaurant })),
    ...(restaurant ? [{ label: "餐厅", poi: restaurant }] : []),
    ...(drink ? [{ label: "饮品", poi: drink }] : []),
    ...deliveryItems.map((poi) => ({ label: "外卖/闪送", poi })),
  ];

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

      {poiCards.length > 0 && (
        <div className="space-y-2">
          {poiCards.map(({ label, poi }, index) => {
            const mapPoi = toMapPoi(poi);
            const imageUrl = firstString(poi.image_url) ?? firstString((poi.images as unknown[] | undefined)?.[0]);
            const active = mapPoi && selectedPoiId === mapPoi.id;
            return (
              <button
                key={`${label}-${firstString(poi.id) ?? index}`}
                type="button"
                onClick={() => mapPoi && onPoiSelect?.(mapPoi)}
                disabled={!mapPoi || !onPoiSelect}
                className={`flex w-full gap-3 rounded border p-3 text-left transition ${
                  active
                    ? "border-blue-500 bg-blue-50"
                    : "border-slate-200 bg-white hover:border-blue-300 hover:bg-slate-50"
                } disabled:cursor-default disabled:hover:border-slate-200 disabled:hover:bg-white`}
              >
                <div className="h-20 w-24 shrink-0 overflow-hidden rounded bg-slate-100">
                  {imageUrl ? (
                    <img
                      src={imageUrl}
                      alt={firstString(poi.name) ?? firstString(poi.merchant_name) ?? "店铺图片"}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="grid h-full w-full place-items-center text-xs text-slate-400">
                      暂无图片
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
                      {label}
                    </span>
                    {firstString(poi.category) && (
                      <span className="truncate text-xs text-slate-500">{firstString(poi.category)}</span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm font-semibold text-slate-900">
                    {firstString(poi.name) ?? firstString(poi.merchant_name)}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    {typeof poi.rating === "number" && (
                      <span className="rounded bg-blue-600 px-1.5 py-0.5 font-semibold text-white">
                        {poi.rating.toFixed(1)}分
                      </span>
                    )}
                    {typeof poi.review_count === "number" && <span>{poi.review_count}条点评</span>}
                    {typeof poi.avg_price === "number" && <span>￥{poi.avg_price}/人</span>}
                  </div>
                  {firstString(poi.address) && (
                    <p className="mt-1 truncate text-xs text-slate-400">{firstString(poi.address)}</p>
                  )}
                </div>
              </button>
            );
          })}
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

function toMapPoi(poi: Record<string, unknown>): MapPoi | null {
  const id = firstString(poi.id) ?? firstString(poi.poi_id) ?? firstString(poi.name);
  const name = firstString(poi.name) ?? firstString(poi.merchant_name);
  const lat = typeof poi.lat === "number" ? poi.lat : Number(poi.lat);
  const lng = typeof poi.lng === "number" ? poi.lng : Number(poi.lng);
  if (!id || !name || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return {
    id,
    name,
    lat,
    lng,
    address: firstString(poi.address),
    category: firstString(poi.category),
    image_url: firstString(poi.image_url),
  };
}

function firstString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}
