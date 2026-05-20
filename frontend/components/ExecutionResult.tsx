"use client";

import type { BookingResult, OrderResult } from "@/types/agent";

export default function ExecutionResult({
  bookings,
  orders,
  shareMessage,
  onCopy,
  copied,
}: {
  bookings: BookingResult[];
  orders: OrderResult[];
  shareMessage: string | null;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm space-y-3">
      <h3 className="font-semibold">执行结果</h3>

      {/* 预约 */}
      {bookings.length > 0 && (
        <div>
          <p className="text-sm font-medium text-gray-600 mb-1">预约 / 订位:</p>
          {bookings.map((b, i) => (
            <div
              key={i}
              className={`text-xs px-2 py-1 rounded mb-1 ${
                b.success
                  ? "bg-green-50 text-green-800"
                  : b.skipped
                  ? "bg-gray-50 text-gray-500"
                  : "bg-red-50 text-red-700"
              }`}
            >
              [{b.type}] {b.poi_name}: {b.message}
            </div>
          ))}
        </div>
      )}

      {/* 订单 */}
      {orders.length > 0 && (
        <div>
          <p className="text-sm font-medium text-gray-600 mb-1">Mock 订单:</p>
          {orders.map((o, i) => (
            <div key={i} className="text-xs bg-blue-50 text-blue-800 px-2 py-1 rounded mb-1">
              {o.deal_title}: {o.order_id}
            </div>
          ))}
        </div>
      )}

      {/* 转发消息 */}
      {shareMessage && (
        <div>
          <p className="text-sm font-medium text-gray-600 mb-1">转发消息:</p>
          <div className="text-sm bg-gray-50 p-3 rounded whitespace-pre-wrap">
            {shareMessage}
          </div>
          <button
            onClick={onCopy}
            className="mt-2 text-xs px-3 py-1 bg-gray-200 rounded hover:bg-gray-300"
          >
            {copied ? "已复制" : "复制转发消息"}
          </button>
        </div>
      )}
    </div>
  );
}
