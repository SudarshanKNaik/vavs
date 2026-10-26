"use client";

import "leaflet/dist/leaflet.css";

import { useEffect, useRef } from "react";
import L from "leaflet";
import type { OutbreakLevel } from "@/services/api";
import { LEVELS } from "./theme";

export type OutbreakMapPoint = {
  locality: string;
  lat: number;
  lon: number;
  cases: number;
  level: OutbreakLevel;
  breakdown: { label: string; count: number }[];
};

interface Props {
  points: OutbreakMapPoint[];
  selected: string | null;
  onSelect: (locality: string) => void;
}

// Hubli-Dharwad twin city.
const DEFAULT_CENTER: [number, number] = [15.395, 75.08];

function tooltipContent(point: OutbreakMapPoint): HTMLDivElement {
  const wrapper = document.createElement("div");
  wrapper.className = "ow-tip";
  const title = document.createElement("p");
  title.className = "ow-tip-title";
  title.textContent = point.locality;
  wrapper.appendChild(title);

  const level = document.createElement("p");
  level.className = "ow-tip-level";
  level.textContent = `${LEVELS[point.level].label} · ${point.cases} case${point.cases === 1 ? "" : "s"} in 7 days`;
  wrapper.appendChild(level);

  point.breakdown.forEach((row) => {
    const line = document.createElement("p");
    line.className = "ow-tip-row";
    line.textContent = `${row.label}: ${row.count}`;
    wrapper.appendChild(line);
  });
  return wrapper;
}

export default function OutbreakMap({ points, selected, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  // Areas the map was last fitted to; refit when they change (e.g. another city).
  const fittedKeyRef = useRef("");

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, scrollWheelZoom: false }).setView(DEFAULT_CENTER, 12);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 19,
    }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      fittedKeyRef.current = "";
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    const maxCases = Math.max(1, ...points.map((p) => p.cases));
    // Quiet areas first so hotspots are drawn on top.
    const ordered = [...points].sort((a, b) => a.cases - b.cases);

    // Risk zones under every marker: red for alerts, amber for watch. Sized in
    // metres so they cover the neighbourhood at any zoom; stacked rings fade
    // from the centre outwards like a heatmap.
    ordered
      .filter((point) => point.level !== "normal" && point.cases > 0)
      .forEach((point) => {
        const zone = 600 + 1100 * Math.sqrt(point.cases / maxCases);
        [1, 0.72, 0.45].forEach((scale) => {
          L.circle([point.lat, point.lon], {
            radius: zone * scale,
            stroke: scale === 1,
            color: LEVELS[point.level].color,
            weight: 1,
            opacity: 0.35,
            dashArray: "4 4",
            fillColor: LEVELS[point.level].color,
            fillOpacity: point.level === "alert" ? 0.12 : 0.1,
            interactive: false,
          }).addTo(layer);
        });
      });

    ordered.forEach((point) => {
      const color = LEVELS[point.level].color;
      const isSelected = selected === point.locality;
      // Area of the circle tracks the case count.
      const radius = 10 + 26 * Math.sqrt(point.cases / maxCases);

      if (point.level === "alert") {
        L.marker([point.lat, point.lon], {
          interactive: false,
          icon: L.divIcon({
            className: "",
            html: `<span class="ow-pulse" style="--ow-size:${Math.round(radius * 2)}px;--ow-color:${color}"></span>`,
            iconSize: [0, 0],
          }),
        }).addTo(layer);
      }

      L.circleMarker([point.lat, point.lon], {
        radius: point.cases > 0 ? radius : 5,
        color: isSelected ? "#2C2420" : "#FAF8F5",
        weight: isSelected ? 3 : 2,
        fillColor: color,
        fillOpacity: point.cases > 0 ? 0.85 : 0.4,
      })
        .bindTooltip(tooltipContent(point), { direction: "top", offset: [0, -radius], opacity: 1, className: "ow-tooltip" })
        .on("click", () => onSelect(point.locality))
        .addTo(layer);

      if (point.cases > 0) {
        L.marker([point.lat, point.lon], {
          interactive: false,
          icon: L.divIcon({
            className: "ow-count",
            html: `<span>${point.cases}</span>`,
            iconSize: [0, 0],
          }),
        }).addTo(layer);
      }
    });

    const key = points.map((p) => p.locality).sort().join("|");
    if (key && key !== fittedKeyRef.current) {
      if (points.length === 1) map.setView([points[0].lat, points[0].lon], 13);
      else map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon] as [number, number])), { padding: [56, 56] });
      fittedKeyRef.current = key;
    }
  }, [points, selected, onSelect]);

  return <div ref={containerRef} className="h-full min-h-[420px] w-full" aria-label="Map of symptom reports by area" />;
}
