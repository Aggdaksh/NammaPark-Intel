"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { loadMapSupport, loadOperationsData } from "@/lib/api";
import { formatNumber, hourlyRisk, padHour, riskColor } from "@/lib/format";
import type { Cluster, MapRoads, MapsConfig, OperationsData, PatrolRoute, RoadSegment } from "@/types/api";

declare global {
  interface Window {
    google?: any;
    __nammaParkGoogleMapsReady?: () => void;
  }
}

let googleMapsPromise: Promise<any> | null = null;

type PointHit = {
  x: number;
  y: number;
  radius: number;
  clusterId: number;
};

type Bounds = {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
};

const routePalette = ["#145c8c", "#0d766d", "#c38119"];

function loadGoogleMaps(apiKey: string) {
  if (window.google?.maps) return Promise.resolve(window.google.maps);
  if (googleMapsPromise) return googleMapsPromise;

  googleMapsPromise = new Promise((resolve, reject) => {
    window.__nammaParkGoogleMapsReady = () => resolve(window.google?.maps);
    const script = document.createElement("script");
    const params = new URLSearchParams({
      key: apiKey,
      loading: "async",
      callback: "__nammaParkGoogleMapsReady",
      v: "weekly"
    });
    script.src = `https://maps.googleapis.com/maps/api/js?${params.toString()}`;
    script.async = true;
    script.onerror = () => reject(new Error("Google Maps JavaScript API failed to load"));
    document.head.appendChild(script);
  });

  return googleMapsPromise;
}

function computeBounds(clusters: Cluster[]): Bounds {
  if (!clusters.length) {
    return { minLat: 12.86, maxLat: 13.08, minLon: 77.48, maxLon: 77.74 };
  }
  const lats = clusters.map((cluster) => Number(cluster.centroid_lat));
  const lons = clusters.map((cluster) => Number(cluster.centroid_lon));
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latPad = Math.max((maxLat - minLat) * 0.2, 0.025);
  const lonPad = Math.max((maxLon - minLon) * 0.2, 0.025);
  return {
    minLat: minLat - latPad,
    maxLat: maxLat + latPad,
    minLon: minLon - lonPad,
    maxLon: maxLon + lonPad
  };
}

function project(canvas: HTMLCanvasElement, bounds: Bounds, lat: number, lon: number) {
  const pad = Math.min(canvas.width, canvas.height) * 0.07;
  const x = pad + ((lon - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * (canvas.width - pad * 2);
  const y = canvas.height - pad - ((lat - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * (canvas.height - pad * 2);
  return { x, y };
}

function resizeCanvas(canvas: HTMLCanvasElement) {
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  const width = Math.max(420, Math.floor(rect.width * scale));
  const height = Math.max(420, Math.floor(rect.height * scale));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
}

function roadStyle(tier: string, width: number) {
  if (tier === "arterial") return { color: "rgba(13, 43, 72, 0.72)", lineWidth: Math.max(1.8, width / 620) };
  if (tier === "collector") return { color: "rgba(65, 87, 106, 0.48)", lineWidth: Math.max(1.1, width / 780) };
  return { color: "rgba(113, 124, 133, 0.26)", lineWidth: Math.max(0.7, width / 1200) };
}

function drawRoads(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, bounds: Bounds, segments: RoadSegment[]) {
  ["local", "collector", "arterial"].forEach((tier) => {
    const style = roadStyle(tier, canvas.width);
    ctx.strokeStyle = style.color;
    ctx.lineWidth = style.lineWidth;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    segments.forEach((segment) => {
      if (segment.tier !== tier || !segment.coords?.length) return;
      ctx.beginPath();
      segment.coords.forEach(([lon, lat], index) => {
        const point = project(canvas, bounds, lat, lon);
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
    });
  });
}

function drawRoutes(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  bounds: Bounds,
  routes: PatrolRoute[],
  showRoutes: boolean
) {
  if (!showRoutes) return;
  routes.forEach((route, index) => {
    const coordinates = route.geojson?.coordinates || [];
    if (coordinates.length < 2) return;
    const color = routePalette[index % routePalette.length];
    ctx.beginPath();
    coordinates.forEach(([lon, lat], pointIndex) => {
      const point = project(canvas, bounds, lat, lon);
      if (pointIndex === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.strokeStyle = "rgba(255, 255, 255, 0.88)";
    ctx.lineWidth = Math.max(8, canvas.width / 190);
    ctx.setLineDash([]);
    ctx.stroke();

    ctx.beginPath();
    coordinates.forEach(([lon, lat], pointIndex) => {
      const point = project(canvas, bounds, lat, lon);
      if (pointIndex === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(4, canvas.width / 360);
    ctx.setLineDash([Math.max(12, canvas.width / 92), Math.max(8, canvas.width / 150)]);
    ctx.stroke();
    ctx.setLineDash([]);

    const labelCoordinate = coordinates[Math.floor(coordinates.length / 2)];
    if (labelCoordinate) {
      const labelPoint = project(canvas, bounds, labelCoordinate[1], labelCoordinate[0]);
      const label = route.unit_id || `BT-${index + 1}`;
      const fontSize = Math.max(12, Math.min(16, canvas.width / 104));
      ctx.font = `800 ${fontSize}px Aptos, Segoe UI, sans-serif`;
      const width = ctx.measureText(label).width + 18;
      const height = fontSize + 12;
      ctx.fillStyle = "rgba(255, 253, 248, 0.94)";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.roundRect(labelPoint.x - width / 2, labelPoint.y - height / 2, width, height, 7);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#0b2438";
      ctx.fillText(label, labelPoint.x - width / 2 + 9, labelPoint.y + fontSize / 2 - 3);
    }
  });
}

function markerSides(risk: number, selected = false) {
  if (selected || risk >= 75) return 6;
  if (risk >= 55) return 4;
  return 5;
}

function markerRotation(sides: number) {
  if (sides === 4) return Math.PI / 4;
  if (sides === 5) return -Math.PI / 2;
  return Math.PI / 6;
}

function drawRegularPolygon(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, sides: number) {
  const rotation = markerRotation(sides);
  ctx.beginPath();
  for (let index = 0; index < sides; index += 1) {
    const angle = rotation + (Math.PI * 2 * index) / sides;
    const pointX = x + Math.cos(angle) * radius;
    const pointY = y + Math.sin(angle) * radius;
    if (index === 0) ctx.moveTo(pointX, pointY);
    else ctx.lineTo(pointX, pointY);
  }
  ctx.closePath();
}

function googlePolygonPath(
  center: { lat: number; lng: number },
  radiusMeters: number,
  sides: number
) {
  const rotation = markerRotation(sides);
  const latRadius = radiusMeters / 111_320;
  const lngRadius = radiusMeters / (111_320 * Math.cos((center.lat * Math.PI) / 180));
  return Array.from({ length: sides }, (_, index) => {
    const angle = rotation + (Math.PI * 2 * index) / sides;
    return {
      lat: center.lat + Math.sin(angle) * latRadius,
      lng: center.lng + Math.cos(angle) * lngRadius
    };
  });
}

function drawHotspots(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  bounds: Bounds,
  clusters: Cluster[],
  selectedClusterId: number | null,
  replayHour: number,
  showAnomalies: boolean,
  pointCache: PointHit[]
) {
  pointCache.length = 0;
  [...clusters].reverse().forEach((cluster) => {
    const point = project(canvas, bounds, Number(cluster.centroid_lat), Number(cluster.centroid_lon));
    const risk = hourlyRisk(cluster, replayHour);
    const color = riskColor(risk);
    const isSelected = cluster.cluster_id === selectedClusterId;
    const haloRadius = Math.max(22, Math.min(64, 17 + risk * 0.42)) * (canvas.width / 1500);
    const sides = markerSides(risk, isSelected);
    pointCache.push({ ...point, radius: haloRadius + 12, clusterId: cluster.cluster_id });

    drawRegularPolygon(ctx, point.x, point.y, haloRadius, sides);
    ctx.fillStyle = `${color}2b`;
    ctx.fill();
    ctx.strokeStyle = isSelected ? "#0b2b49" : `${color}78`;
    ctx.lineWidth = isSelected ? Math.max(3, canvas.width / 430) : Math.max(1.5, canvas.width / 980);
    ctx.stroke();

    drawRegularPolygon(ctx, point.x, point.y, Math.max(8, haloRadius * 0.28), sides);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = isSelected ? "#0b2b49" : "rgba(16, 34, 50, 0.34)";
    ctx.lineWidth = isSelected ? 3 : 1.5;
    ctx.stroke();

    drawRegularPolygon(ctx, point.x, point.y, Math.max(5, haloRadius * 0.18), sides);
    ctx.fillStyle = color;
    ctx.fill();

    if (showAnomalies && cluster.is_anomaly) {
      ctx.beginPath();
      ctx.arc(point.x + haloRadius * 0.62, point.y - haloRadius * 0.62, Math.max(5, haloRadius * 0.16), 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
      ctx.strokeStyle = "#b64232";
      ctx.lineWidth = Math.max(2, canvas.width / 720);
      ctx.stroke();
    }

    if (isSelected) {
      const label = `Cluster ${cluster.cluster_id}`;
      const fontSize = Math.max(13, Math.min(18, canvas.width / 86));
      ctx.font = `700 ${fontSize}px Aptos, Segoe UI, sans-serif`;
      const labelWidth = ctx.measureText(label).width + 24;
      const labelHeight = fontSize + 16;
      const labelX = Math.min(point.x + haloRadius + 12, canvas.width - labelWidth - 18);
      const labelY = Math.max(18, Math.min(point.y - labelHeight / 2, canvas.height - labelHeight - 18));
      ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
      ctx.strokeStyle = "rgba(12, 37, 64, 0.22)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(labelX, labelY, labelWidth, labelHeight, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#0b2b49";
      ctx.fillText(label, labelX + 12, labelY + labelHeight - 10);
    }
  });
}

export function MapClient() {
  const [operations, setOperations] = useState<OperationsData | null>(null);
  const [roads, setRoads] = useState<MapRoads>({ segments: [] });
  const [mapsConfig, setMapsConfig] = useState<MapsConfig>({ provider: "local-osm" });
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);
  const [replayHour, setReplayHour] = useState(17);
  const [showRoutes, setShowRoutes] = useState(true);
  const [showAnomalies, setShowAnomalies] = useState(true);
  const [mapMode, setMapMode] = useState<"google" | "local-osm">("local-osm");
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const googleMapRef = useRef<HTMLDivElement | null>(null);
  const googleInstanceRef = useRef<any>(null);
  const googleOverlaysRef = useRef<any[]>([]);
  const pointCacheRef = useRef<PointHit[]>([]);

  useEffect(() => {
    Promise.all([loadOperationsData(), loadMapSupport()])
      .then(([nextOperations, support]) => {
        setOperations(nextOperations);
        setSelectedClusterId(nextOperations.hotspots[0]?.cluster_id || null);
        setRoads(support.roads);
        setMapsConfig(support.config);
      })
      .catch((nextError) => setError(nextError.message || "Unable to load map data."));
  }, []);

  const selectedCluster = useMemo(() => {
    if (!operations || selectedClusterId === null) return operations?.hotspots[0] || null;
    return operations.clusters[String(selectedClusterId)] || operations.hotspots.find((cluster) => cluster.cluster_id === selectedClusterId) || null;
  }, [operations, selectedClusterId]);

  const bounds = useMemo(() => computeBounds(operations?.hotspots || []), [operations]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !operations) return;

    function draw() {
      const nextCanvas = canvasRef.current;
      if (!nextCanvas || !operations) return;
      resizeCanvas(nextCanvas);
      const ctx = nextCanvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, nextCanvas.width, nextCanvas.height);
      ctx.fillStyle = "#ede6d8";
      ctx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
      ctx.strokeStyle = "rgba(16, 43, 73, 0.06)";
      ctx.lineWidth = 1;
      const grid = Math.max(42, nextCanvas.width / 24);
      for (let x = 0; x <= nextCanvas.width; x += grid) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, nextCanvas.height);
        ctx.stroke();
      }
      for (let y = 0; y <= nextCanvas.height; y += grid) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(nextCanvas.width, y);
        ctx.stroke();
      }
      drawRoads(ctx, nextCanvas, bounds, roads.segments || []);
      drawRoutes(ctx, nextCanvas, bounds, operations.routes, showRoutes);
      drawHotspots(
        ctx,
        nextCanvas,
        bounds,
        operations.hotspots,
        selectedClusterId,
        replayHour,
        showAnomalies,
        pointCacheRef.current
      );
    }

    function handleClick(event: MouseEvent) {
      const activeCanvas = canvasRef.current;
      if (!activeCanvas) return;
      const rect = activeCanvas.getBoundingClientRect();
      const scaleX = activeCanvas.width / rect.width;
      const scaleY = activeCanvas.height / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      const hit = pointCacheRef.current.find((point) => Math.hypot(point.x - x, point.y - y) <= point.radius);
      if (hit) setSelectedClusterId(hit.clusterId);
    }

    draw();
    window.addEventListener("resize", draw);
    canvas.addEventListener("click", handleClick);
    return () => {
      window.removeEventListener("resize", draw);
      canvas.removeEventListener("click", handleClick);
    };
  }, [bounds, operations, roads, replayHour, selectedClusterId, showAnomalies, showRoutes]);

  useEffect(() => {
    const apiKey = mapsConfig.google_maps_api_key;
    if (!apiKey || !operations || !googleMapRef.current) {
      setMapMode("local-osm");
      return;
    }

    loadGoogleMaps(apiKey)
      .then((maps) => {
        if (!googleMapRef.current) return;
        if (!googleInstanceRef.current) {
          const center = operations.hotspots[0]
            ? { lat: Number(operations.hotspots[0].centroid_lat), lng: Number(operations.hotspots[0].centroid_lon) }
            : { lat: 12.9716, lng: 77.5946 };
          googleInstanceRef.current = new maps.Map(googleMapRef.current, {
            center,
            zoom: 12,
            minZoom: 10,
            maxZoom: 18,
            mapId: mapsConfig.google_maps_map_id || undefined,
            gestureHandling: "greedy",
            fullscreenControl: true,
            mapTypeControl: false,
            streetViewControl: false,
            clickableIcons: false,
            styles: mapsConfig.google_maps_map_id
              ? undefined
              : [
                  { featureType: "poi", stylers: [{ visibility: "off" }] },
                  { featureType: "transit", stylers: [{ visibility: "off" }] },
                  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
                  { featureType: "road.arterial", elementType: "geometry", stylers: [{ color: "#d5dee6" }] },
                  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#c2d0d9" }] },
                  { featureType: "landscape", elementType: "geometry", stylers: [{ color: "#eef0eb" }] },
                  { featureType: "water", elementType: "geometry", stylers: [{ color: "#c9dce4" }] }
                ]
          });
          const googleBounds = new maps.LatLngBounds();
          operations.hotspots.forEach((cluster) => {
            googleBounds.extend({ lat: Number(cluster.centroid_lat), lng: Number(cluster.centroid_lon) });
          });
          if (!googleBounds.isEmpty()) googleInstanceRef.current.fitBounds(googleBounds, 56);
        }
        setMapMode("google");
      })
      .catch(() => setMapMode("local-osm"));
  }, [mapsConfig, operations]);

  useEffect(() => {
    const apiKey = mapsConfig.google_maps_api_key;
    if (mapMode !== "google" || !apiKey || !operations || !googleInstanceRef.current || !window.google?.maps) return;
    const maps = window.google.maps;
    const map = googleInstanceRef.current;
    googleOverlaysRef.current.forEach((overlay) => overlay.setMap(null));
    googleOverlaysRef.current = [];

    if (showRoutes) {
      operations.routes.forEach((route, index) => {
        const path = (route.geojson?.coordinates || []).map(([lng, lat]) => ({ lat, lng }));
        if (path.length < 2) return;
        const casing = new maps.Polyline({
          path,
          geodesic: true,
          clickable: false,
          strokeColor: "#ffffff",
          strokeOpacity: 0.9,
          strokeWeight: 8,
          zIndex: 20,
          map
        });
        const line = new maps.Polyline({
          path,
          geodesic: true,
          strokeColor: routePalette[index % routePalette.length],
          strokeOpacity: 0.9,
          strokeWeight: 4,
          zIndex: 21,
          map
        });
        googleOverlaysRef.current.push(casing, line);
        const midpoint = path[Math.floor(path.length / 2)];
        if (midpoint) {
          const marker = new maps.Marker({
            position: midpoint,
            map,
            label: {
              text: route.unit_id || `BT-${index + 1}`,
              color: "#0b2438",
              fontWeight: "800",
              fontSize: "12px"
            },
            icon: {
              path: maps.SymbolPath.CIRCLE,
              scale: 0,
              fillOpacity: 0,
              strokeOpacity: 0
            },
            zIndex: 44
          });
          googleOverlaysRef.current.push(marker);
        }
      });
    }

    operations.hotspots.forEach((cluster) => {
      const risk = hourlyRisk(cluster, replayHour);
      const color = riskColor(risk);
      const selected = cluster.cluster_id === selectedClusterId;
      const center = { lat: Number(cluster.centroid_lat), lng: Number(cluster.centroid_lon) };
      const radiusMeters = Math.max(180, Math.min(820, 155 + risk * 6.4));
      const sides = markerSides(risk, selected);
      const halo = new maps.Polygon({
        paths: googlePolygonPath(center, radiusMeters, sides),
        strokeColor: selected ? "#0b2b49" : color,
        strokeOpacity: selected ? 0.9 : 0.42,
        strokeWeight: selected ? 3.4 : 1.5,
        fillColor: color,
        fillOpacity: selected ? 0.28 : 0.17,
        zIndex: selected ? 55 : 35,
        map
      });
      halo.addListener("click", () => setSelectedClusterId(cluster.cluster_id));
      googleOverlaysRef.current.push(halo);
      const core = new maps.Polygon({
        paths: googlePolygonPath(center, Math.max(52, radiusMeters * 0.22), sides),
        strokeColor: selected ? "#0b2b49" : "rgba(16, 34, 50, 0.42)",
        strokeOpacity: 0.95,
        strokeWeight: selected ? 2.5 : 1.5,
        fillColor: "#ffffff",
        fillOpacity: 0.96,
        zIndex: selected ? 75 : 50,
        map
      });
      core.addListener("click", () => setSelectedClusterId(cluster.cluster_id));
      googleOverlaysRef.current.push(core);
      const centerShape = new maps.Polygon({
        paths: googlePolygonPath(center, Math.max(34, radiusMeters * 0.14), sides),
        strokeColor: color,
        strokeOpacity: 0.98,
        strokeWeight: 1.2,
        fillColor: color,
        fillOpacity: 0.98,
        zIndex: selected ? 85 : 58,
        map
      });
      centerShape.addListener("click", () => setSelectedClusterId(cluster.cluster_id));
      googleOverlaysRef.current.push(centerShape);
      if (showAnomalies && cluster.is_anomaly) {
        const marker = new maps.Marker({
          position: center,
          map,
          title: `Exception alert cluster ${cluster.cluster_id}`,
          icon: {
            path: maps.SymbolPath.CIRCLE,
            scale: selected ? 7 : 5,
            fillColor: "#ffffff",
            fillOpacity: 1,
            strokeColor: "#b64232",
            strokeWeight: 2
          },
          zIndex: selected ? 80 : 60
        });
        marker.addListener("click", () => setSelectedClusterId(cluster.cluster_id));
        googleOverlaysRef.current.push(marker);
      }
    });
  }, [mapMode, mapsConfig.google_maps_api_key, operations, replayHour, selectedClusterId, showAnomalies, showRoutes]);

  if (error) return <div className="notice error">{error}</div>;
  if (!operations) return <div className="notice">Loading geospatial view...</div>;

  return (
    <div className="map-layout">
      <section className="map-toolbar">
        <div>
          <span className="eyebrow">Geospatial command</span>
          <h1>Hotspots and patrol overlays</h1>
        </div>
        <div className="map-controls">
          <label>
            Replay hour
            <input
              type="range"
              min={0}
              max={23}
              value={replayHour}
              onChange={(event) => setReplayHour(Number(event.target.value))}
            />
            <strong>{padHour(replayHour)}</strong>
          </label>
          <button type="button" className={showRoutes ? "active" : ""} onClick={() => setShowRoutes((value) => !value)}>
            Routes
          </button>
          <button type="button" className={showAnomalies ? "active" : ""} onClick={() => setShowAnomalies((value) => !value)}>
            Alerts
          </button>
        </div>
      </section>
      <div className="map-workspace">
        <aside className="map-sidebar">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Queue</span>
              <h2>Priority clusters</h2>
            </div>
            <span className="badge">{operations.hotspots.length}</span>
          </div>
          <div className="map-cluster-list">
            {operations.hotspots.slice(0, 12).map((cluster, index) => {
              const active = cluster.cluster_id === selectedClusterId;
              const color = riskColor(cluster.final_risk_0_100);
              return (
                <button
                  key={cluster.cluster_id}
                  type="button"
                  className={active ? "active" : ""}
                  onClick={() => setSelectedClusterId(cluster.cluster_id)}
                >
                  <span>{index + 1}</span>
                  <strong>Cluster {cluster.cluster_id}</strong>
                  <small>{cluster.police_station}</small>
                  <em style={{ backgroundColor: color }}>{Math.round(cluster.final_risk_0_100)}</em>
                </button>
              );
            })}
          </div>
        </aside>
        <section className="map-surface">
          <div className="map-status-bar">
            <span>{mapMode === "google" ? "Google Maps overlay" : "Local OSM overlay"}</span>
            <span>{formatNumber(roads.metadata?.segment_count || roads.segments.length)} road segments</span>
            <span>{selectedCluster ? `Selected cluster ${selectedCluster.cluster_id}` : "No cluster selected"}</span>
          </div>
          <div ref={googleMapRef} className={`google-map ${mapMode === "google" ? "active" : ""}`} />
          <canvas ref={canvasRef} className={`local-map ${mapMode === "google" ? "hidden" : ""}`} />
          <div className="map-legend">
            <span><i className="shape-pentagon low" /> Low</span>
            <span><i className="shape-diamond watch" /> Watch</span>
            <span><i className="shape-hex critical" /> Critical</span>
            <span><i className="route-line" /> Patrol route</span>
          </div>
        </section>
        <aside className="map-detail">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Selection</span>
              <h2>{selectedCluster ? `Cluster ${selectedCluster.cluster_id}` : "Cluster detail"}</h2>
            </div>
          </div>
          {selectedCluster ? (
            <>
              <div className="detail-grid compact">
                <div>
                  <span>Risk</span>
                  <strong>{Math.round(selectedCluster.final_risk_0_100)}/100</strong>
                </div>
                <div>
                  <span>Delay</span>
                  <strong>{formatNumber(selectedCluster.predicted_delay_min, 4)} min</strong>
                </div>
                <div>
                  <span>Station</span>
                  <strong>{selectedCluster.police_station}</strong>
                </div>
                <div>
                  <span>Records</span>
                  <strong>{formatNumber(selectedCluster.total_violations)}</strong>
                </div>
              </div>
              <p className="panel-note">
                {selectedCluster.dominant_violation_type} involving {selectedCluster.dominant_vehicle_type}.{" "}
                {selectedCluster.is_anomaly
                  ? `Exception score: ${selectedCluster.anomaly_zscore} sigma above baseline.`
                  : "No exception alert active."}
              </p>
              <div className="map-detail-actions">
                <Link className="primary-button" href={`/commander?prompt=${encodeURIComponent(`Brief cluster ${selectedCluster.cluster_id}`)}`}>
                  Ask commander
                </Link>
              </div>
            </>
          ) : (
            <p className="panel-note">Select a hotspot marker to inspect the cluster.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
