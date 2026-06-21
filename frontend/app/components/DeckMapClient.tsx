"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { PathLayer } from "@deck.gl/layers";
import { loadOperationsData } from "@/lib/api";
import { formatNumber, hourlyRisk, padHour, riskColor } from "@/lib/format";
import type { OperationsData, Cluster } from "@/types/api";

declare const google: any;

const GOOGLE_MAPS_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "";

function loadGoogleMapsScript(apiKey: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") return reject();
    if ((window as any).__googleMapsLoaded) return resolve();
    if (document.getElementById("google-maps-script")) {
      // Already loading, wait for it
      const check = setInterval(() => {
        if ((window as any).__googleMapsLoaded) {
          clearInterval(check);
          resolve();
        }
      }, 100);
      return;
    }
    const script = document.createElement("script");
    script.id = "google-maps-script";
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}`;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      (window as any).__googleMapsLoaded = true;
      resolve();
    };
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

export function DeckMapClient() {
  const mapRef = useRef<HTMLDivElement>(null);
  const googleMapRef = useRef<any>(null);
  const overlayRef = useRef<GoogleMapsOverlay | null>(null);

  const [operations, setOperations] = useState<OperationsData | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);
  const [replayHour, setReplayHour] = useState(17);
  const [showRoutes, setShowRoutes] = useState(true);
  const [mapReady, setMapReady] = useState(false);

  // Load operations data
  useEffect(() => {
    loadOperationsData().then((data) => {
      setOperations(data);
      if (data.hotspots.length > 0) {
        setSelectedClusterId(data.hotspots[0].cluster_id);
      }
    });
  }, []);

  // Load Google Maps script then init map
  useEffect(() => {
    if (!mapRef.current) return;
    loadGoogleMapsScript(GOOGLE_MAPS_API_KEY).then(() => {
      if (!mapRef.current || googleMapRef.current) return;
      const map = new google.maps.Map(mapRef.current, {
        center: { lat: 12.9716, lng: 77.5946 },
        zoom: 12,
        mapTypeId: "roadmap",
        styles: [
          { elementType: "geometry", stylers: [{ color: "#1a1a2e" }] },
          { elementType: "labels.text.fill", stylers: [{ color: "#a0aec0" }] },
          { elementType: "labels.text.stroke", stylers: [{ color: "#1a1a2e" }] },
          { featureType: "road", elementType: "geometry", stylers: [{ color: "#2d3748" }] },
          { featureType: "road.arterial", elementType: "geometry", stylers: [{ color: "#3a4a6b" }] },
          { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#4a5568" }] },
          { featureType: "water", elementType: "geometry", stylers: [{ color: "#0f2a4a" }] },
          { featureType: "poi", stylers: [{ visibility: "off" }] },
          { featureType: "transit", stylers: [{ visibility: "off" }] },
          {
            featureType: "administrative",
            elementType: "geometry.stroke",
            stylers: [{ color: "#4a5568" }],
          },
        ],
        disableDefaultUI: false,
        zoomControl: true,
        streetViewControl: false,
        mapTypeControl: false,
        fullscreenControl: false,
      });
      googleMapRef.current = map;

      const overlay = new GoogleMapsOverlay({ layers: [] });
      overlay.setMap(map);
      overlayRef.current = overlay;
      setMapReady(true);
    });
  }, []);

  // Build Deck.gl layers
  const layers = useMemo(() => {
    if (!operations) return [];

    const h3Data = operations.hotspots
      .map((cluster) => ({
        hex: cluster.h3_res9 || cluster.h3_res8,
        risk: hourlyRisk(cluster, replayHour),
        clusterId: cluster.cluster_id,
        station: cluster.police_station,
        records: cluster.total_violations,
      }))
      .filter((d) => d.hex);

    const routesData = showRoutes
      ? operations.routes
          .map((r) => ({
            path: r.geojson?.coordinates || [],
            color: [32, 178, 170] as [number, number, number],
          }))
          .filter((r) => r.path.length > 0)
      : [];

    return [
      new H3HexagonLayer({
        id: "h3-hexagon-layer",
        data: h3Data,
        pickable: true,
        wireframe: false,
        filled: true,
        extruded: true,
        elevationScale: 25,
        getHexagon: (d: any) => d.hex,
        getFillColor: (d: any) => {
          const hex = riskColor(d.risk);
          const r = parseInt(hex.slice(1, 3), 16);
          const g = parseInt(hex.slice(3, 5), 16);
          const b = parseInt(hex.slice(5, 7), 16);
          return [r, g, b, 220];
        },
        getElevation: (d: any) => d.risk * 12,
        onClick: (info: any) => {
          if (info.object) setSelectedClusterId(info.object.clusterId);
        },
        updateTriggers: { getFillColor: replayHour, getElevation: replayHour },
      }),
      new PathLayer({
        id: "patrol-path-layer",
        data: routesData,
        pickable: false,
        widthScale: 15,
        widthMinPixels: 2,
        getPath: (d: any) => d.path,
        getColor: (d: any) => d.color,
        getWidth: () => 2,
      }),
    ];
  }, [operations, replayHour, showRoutes]);

  // Update overlay when layers change
  useEffect(() => {
    if (overlayRef.current && mapReady) {
      overlayRef.current.setProps({ layers });
    }
  }, [layers, mapReady]);

  // Pan map to first hotspot
  useEffect(() => {
    if (googleMapRef.current && operations?.hotspots?.length) {
      const h = operations.hotspots[0];
      googleMapRef.current.panTo({ lat: Number(h.centroid_lat), lng: Number(h.centroid_lon) });
      googleMapRef.current.setZoom(13);
    }
  }, [operations]);

  const selectedCluster: Cluster | null = useMemo(() => {
    if (!operations || selectedClusterId === null) return operations?.hotspots[0] || null;
    return (
      operations.clusters[String(selectedClusterId)] ||
      operations.hotspots.find((h) => h.cluster_id === selectedClusterId) ||
      null
    );
  }, [operations, selectedClusterId]);

  return (
    <div style={{ height: "calc(100vh - 120px)", display: "flex", flexDirection: "column" }}>
      {/* Toolbar */}
      <section className="map-toolbar">
        <div>
          <span className="eyebrow">Geospatial command</span>
          <h1>Parking Hotspot Intelligence Map</h1>
        </div>
        <div className="map-controls">
          <label>
            Replay hour
            <input
              type="range"
              min={0}
              max={23}
              value={replayHour}
              onChange={(e) => setReplayHour(Number(e.target.value))}
            />
            <strong>{padHour(replayHour)}</strong>
          </label>
          <button className={showRoutes ? "active" : ""} onClick={() => setShowRoutes(!showRoutes)}>
            Patrol Routes
          </button>
        </div>
      </section>

      {/* Map + Sidebar */}
      <div style={{ flex: 1, position: "relative", display: "flex" }}>
        {/* Google Map */}
        <div ref={mapRef} style={{ flex: 1, height: "100%" }} />

        {/* Sidebar */}
        {selectedCluster && (
          <div
            style={{
              position: "absolute",
              top: 16,
              right: 16,
              background: "rgba(16, 24, 40, 0.92)",
              backdropFilter: "blur(12px)",
              border: "1px solid rgba(255,255,255,0.1)",
              padding: "20px",
              borderRadius: "12px",
              color: "white",
              width: 280,
              zIndex: 10,
              boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
            }}
          >
            <div
              style={{
                fontSize: "11px",
                color: "#a0aec0",
                textTransform: "uppercase",
                letterSpacing: "1px",
                marginBottom: 8,
              }}
            >
              Selected Cluster
            </div>
            <h3 style={{ margin: "0 0 12px", fontSize: "18px", color: "#e2e8f0" }}>
              Cluster {selectedCluster.cluster_id}
            </h3>
            <div style={{ display: "grid", gap: "10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#a0aec0", fontSize: "13px" }}>Risk Score</span>
                <strong style={{ color: riskColor(selectedCluster.final_risk_0_100), fontSize: "16px" }}>
                  {Math.round(selectedCluster.final_risk_0_100)}/100
                </strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#a0aec0", fontSize: "13px" }}>Station</span>
                <strong style={{ color: "#e2e8f0", fontSize: "13px", textAlign: "right", maxWidth: 160 }}>
                  {selectedCluster.police_station}
                </strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#a0aec0", fontSize: "13px" }}>Violations</span>
                <strong style={{ color: "#e2e8f0" }}>{formatNumber(selectedCluster.total_violations)}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#a0aec0", fontSize: "13px" }}>Predicted delay</span>
                <strong style={{ color: "#e2e8f0" }}>
                  {formatNumber(selectedCluster.predicted_delay_min, 2)} min
                </strong>
              </div>
              {selectedCluster.risk_label && (
                <div
                  style={{
                    marginTop: 4,
                    padding: "6px 12px",
                    borderRadius: 6,
                    textAlign: "center",
                    background: `${riskColor(selectedCluster.final_risk_0_100)}22`,
                    border: `1px solid ${riskColor(selectedCluster.final_risk_0_100)}44`,
                    color: riskColor(selectedCluster.final_risk_0_100),
                    fontSize: "13px",
                    fontWeight: 600,
                  }}
                >
                  {selectedCluster.risk_label}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Loading overlay */}
        {!mapReady && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "rgba(10,15,28,0.8)",
              color: "#a0aec0",
              fontSize: "14px",
            }}
          >
            Loading map...
          </div>
        )}
      </div>
    </div>
  );
}
