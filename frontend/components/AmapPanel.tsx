"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export interface MapPoi {
  id: string;
  name: string;
  address?: string;
  lat: number;
  lng: number;
  category?: string;
  image_url?: string;
}

declare global {
  interface Window {
    AMap?: any;
    __amapLoadingPromise?: Promise<void>;
  }
}

const HONGGUTAN_CENTER: [number, number] = [115.8584, 28.6908];

function loadAmap(key: string, securityCode?: string) {
  if (window.AMap) return Promise.resolve();
  if (window.__amapLoadingPromise) return window.__amapLoadingPromise;

  window.__amapLoadingPromise = new Promise<void>((resolve, reject) => {
    if (securityCode) {
      (window as any)._AMapSecurityConfig = {
        securityJsCode: securityCode,
      };
    }
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("高德地图脚本加载失败"));
    document.head.appendChild(script);
  });

  return window.__amapLoadingPromise;
}

export default function AmapPanel({
  pois,
  selectedPoi,
  onPoiSelect,
}: {
  pois: MapPoi[];
  selectedPoi: MapPoi | null;
  onPoiSelect: (poi: MapPoi) => void;
}) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstance = useRef<any>(null);
  const markersRef = useRef<any[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const amapKey = process.env.NEXT_PUBLIC_AMAP_JS_KEY;
  const amapSecurityCode = process.env.NEXT_PUBLIC_AMAP_SECURITY_CODE;
  const validPois = useMemo(
    () => pois.filter((poi) => Number.isFinite(poi.lat) && Number.isFinite(poi.lng)),
    [pois]
  );

  useEffect(() => {
    if (!amapKey || !mapRef.current) return;

    let cancelled = false;
    loadAmap(amapKey, amapSecurityCode)
      .then(() => {
        if (cancelled || !mapRef.current || !window.AMap) return;
        if (!mapInstance.current) {
          mapInstance.current = new window.AMap.Map(mapRef.current, {
            center: HONGGUTAN_CENTER,
            zoom: 14,
            viewMode: "2D",
          });
        }
      })
      .catch((error: Error) => setLoadError(error.message));

    return () => {
      cancelled = true;
    };
  }, [amapKey, amapSecurityCode]);

  useEffect(() => {
    if (!window.AMap || !mapInstance.current) return;

    markersRef.current.forEach((marker) => marker.setMap(null));
    markersRef.current = validPois.map((poi) => {
      const marker = new window.AMap.Marker({
        map: mapInstance.current,
        position: [poi.lng, poi.lat],
        title: poi.name,
        label: {
          direction: "top",
          content: `<div style="padding:2px 6px;border-radius:4px;background:#2563eb;color:#fff;font-size:12px;">${poi.name}</div>`,
        },
      });
      marker.on("click", () => onPoiSelect(poi));
      return marker;
    });

    if (markersRef.current.length > 1) {
      mapInstance.current.setFitView(markersRef.current, false, [60, 60, 60, 60], 15);
    } else if (markersRef.current.length === 1) {
      const poi = validPois[0];
      mapInstance.current.setZoomAndCenter(16, [poi.lng, poi.lat]);
    } else {
      mapInstance.current.setZoomAndCenter(14, HONGGUTAN_CENTER);
    }
  }, [validPois, onPoiSelect]);

  useEffect(() => {
    if (!selectedPoi || !window.AMap || !mapInstance.current) return;
    mapInstance.current.setZoomAndCenter(17, [selectedPoi.lng, selectedPoi.lat]);
  }, [selectedPoi]);

  if (!amapKey) {
    return (
      <FallbackMap
        pois={validPois}
        selectedPoi={selectedPoi}
        onPoiSelect={onPoiSelect}
        message="未配置 NEXT_PUBLIC_AMAP_JS_KEY，已显示红谷滩坐标预览。"
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div ref={mapRef} className="h-[calc(100vh-260px)] min-h-[420px] w-full" />
      </div>
      {loadError && (
        <FallbackMap
          pois={validPois}
          selectedPoi={selectedPoi}
          onPoiSelect={onPoiSelect}
          message={loadError}
        />
      )}
      {selectedPoi && (
        <SelectedPoiSummary selectedPoi={selectedPoi} />
      )}
    </div>
  );
}

function FallbackMap({
  pois,
  selectedPoi,
  onPoiSelect,
  message,
}: {
  pois: MapPoi[];
  selectedPoi: MapPoi | null;
  onPoiSelect: (poi: MapPoi) => void;
  message: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="relative h-[calc(100vh-260px)] min-h-[420px] overflow-hidden rounded-lg border border-blue-100 bg-[#d9eefc] shadow-sm">
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(255,255,255,.35)_1px,transparent_1px),linear-gradient(rgba(255,255,255,.35)_1px,transparent_1px)] bg-[length:48px_48px]" />
        <div className="absolute left-4 top-4 rounded bg-white/90 px-3 py-2 text-xs text-slate-600 shadow">
          {message}
        </div>
        {pois.map((poi) => {
          const x = 12 + ((poi.lng - 115.79) / 0.09) * 76;
          const y = 82 - ((poi.lat - 28.63) / 0.08) * 68;
          const active = selectedPoi?.id === poi.id;
          return (
            <button
              key={poi.id}
              type="button"
              onClick={() => onPoiSelect(poi)}
              className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white px-2 py-1 text-xs font-semibold shadow ${
                active ? "bg-blue-700 text-white" : "bg-sky-500 text-white"
              }`}
              style={{ left: `${Math.max(8, Math.min(92, x))}%`, top: `${Math.max(10, Math.min(88, y))}%` }}
            >
              {poi.name}
            </button>
          );
        })}
      </div>
      {selectedPoi && <SelectedPoiSummary selectedPoi={selectedPoi} />}
    </div>
  );
}

function SelectedPoiSummary({ selectedPoi }: { selectedPoi: MapPoi }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-blue-700">当前定位</p>
      <h3 className="mt-1 text-lg font-semibold">{selectedPoi.name}</h3>
      {selectedPoi.address && (
        <p className="mt-2 text-sm leading-6 text-slate-600">{selectedPoi.address}</p>
      )}
      <p className="mt-2 font-mono text-xs text-slate-400">
        {selectedPoi.lat.toFixed(6)}, {selectedPoi.lng.toFixed(6)}
      </p>
    </section>
  );
}
