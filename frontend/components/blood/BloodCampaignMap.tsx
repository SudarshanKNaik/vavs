"use client";

import "leaflet/dist/leaflet.css";

import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";

type BasePoint = {
  id?: string;
  name?: string;
  location?: string | null;
  latitude?: number | string | null;
  longitude?: number | string | null;
  status?: string;
  blood_type?: string;
};

interface Props {
  patient?: BasePoint;
  donors: BasePoint[];
  ngos: BasePoint[];
}

type LatLngPoint = {
  lat: number;
  lon: number;
};

const DEFAULT_CENTER: [number, number] = [22.9734, 78.6569];

function buildPopupContent(title: string, lines: string[]): HTMLDivElement {
  const wrapper = document.createElement("div");
  wrapper.className = "text-sm";

  const heading = document.createElement("p");
  heading.className = "font-semibold";
  heading.textContent = title;
  wrapper.appendChild(heading);

  lines.forEach((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    wrapper.appendChild(p);
  });

  return wrapper;
}

function toLatLng(point?: BasePoint): LatLngPoint | null {
  if (!point) return null;
  const lat = Number(point.latitude);
  const lon = Number(point.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

function markerColorByStatus(status?: string): string {
  switch ((status || "").toLowerCase()) {
    case "active":
      return "#f59e0b";
    case "accepted":
      return "#10b981";
    case "completed":
      return "#22c55e";
    case "failed":
      return "#ef4444";
    case "queued":
      return "#3b82f6";
    default:
      return "#6b7280";
  }
}

export default function BloodCampaignMap({ patient, donors, ngos }: Props) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerLayerRef = useRef<L.LayerGroup | null>(null);

  const patientPoint = toLatLng(patient);

  const donorPoints = useMemo(
    () =>
      donors
        .map((donor) => ({ donor, point: toLatLng(donor) }))
        .filter((item): item is { donor: BasePoint; point: LatLngPoint } => item.point !== null),
    [donors],
  );

  const ngoPoints = useMemo(
    () =>
      ngos
        .map((ngo) => ({ ngo, point: toLatLng(ngo) }))
        .filter((item): item is { ngo: BasePoint; point: LatLngPoint } => item.point !== null),
    [ngos],
  );

  const allPoints: LatLngPoint[] = useMemo(
    () => [
      ...(patientPoint ? [patientPoint] : []),
      ...donorPoints.map((item) => item.point),
      ...ngoPoints.map((item) => item.point),
    ],
    [patientPoint, donorPoints, ngoPoints],
  );

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = L.map(mapContainerRef.current, {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView(DEFAULT_CENTER, 5);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    const markerLayer = L.layerGroup().addTo(map);

    mapRef.current = map;
    markerLayerRef.current = markerLayer;

    return () => {
      markerLayer.remove();
      map.remove();
      markerLayerRef.current = null;
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (allPoints.length === 0) {
      map.setView(DEFAULT_CENTER, 5);
      return;
    }

    if (allPoints.length === 1) {
      map.setView([allPoints[0].lat, allPoints[0].lon], 11);
      return;
    }

    const bounds = L.latLngBounds(
      allPoints.map((item) => [item.lat, item.lon] as [number, number]),
    );
    map.fitBounds(bounds, { padding: [24, 24] });
  }, [allPoints]);

  useEffect(() => {
    const markerLayer = markerLayerRef.current;
    if (!markerLayer) return;

    markerLayer.clearLayers();

    if (patientPoint) {
      L.circleMarker([patientPoint.lat, patientPoint.lon], {
        radius: 9,
        color: "#111827",
        fillColor: "#111827",
        fillOpacity: 0.75,
        weight: 2,
      })
        .bindPopup(
          buildPopupContent("Recipient Location", [patient?.location || "Unknown"]),
        )
        .addTo(markerLayer);
    }

    donorPoints.forEach(({ donor, point }) => {
      const status = donor.status || "not-contacted";
      L.circleMarker([point.lat, point.lon], {
        radius: 7,
        color: markerColorByStatus(status),
        fillColor: markerColorByStatus(status),
        fillOpacity: 0.8,
        weight: 2,
      })
        .bindPopup(
          buildPopupContent(donor.name || "Donor", [
            `Blood: ${donor.blood_type || "-"}`,
            `Status: ${status}`,
            donor.location || "Unknown location",
          ]),
        )
        .addTo(markerLayer);
    });

    ngoPoints.forEach(({ ngo, point }) => {
      L.circleMarker([point.lat, point.lon], {
        radius: 8,
        color: "#2563eb",
        fillColor: "#2563eb",
        fillOpacity: 0.65,
        weight: 2,
      })
        .bindPopup(
          buildPopupContent(ngo.name || "NGO", [ngo.location || "Unknown location"]),
        )
        .addTo(markerLayer);
    });
  }, [patient, patientPoint, donorPoints, ngoPoints]);

  return (
    <div
      ref={mapContainerRef}
      className="w-full h-[420px] rounded-xl overflow-hidden border border-border"
    />
  );
}
