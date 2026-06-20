"use client";

import { useEffect, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { PathLayer } from "@deck.gl/layers";
import Map from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import { loadMapSupport, loadOperationsData } from "@/lib/api";
import { formatNumber, hourlyRisk, padHour, riskColor } from "@/lib/format";
import type { OperationsData, PatrolRoute, Cluster } from "@/types/api";

export function DeckMapClient() {
  const [operations, setOperations] = useState<OperationsData | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);
  const [replayHour, setReplayHour] = useState(17);
  const [showRoutes, setShowRoutes] = useState(true);
  const [viewState, setViewState] = useState({
    longitude: 77.5946,
    latitude: 12.9716,
    zoom: 11,
    pitch: 45,
    bearing: 0
  });

  useEffect(() => {
    loadOperationsData().then((data) => {
      setOperations(data);
      if (data.hotspots.length > 0) {
        setSelectedClusterId(data.hotspots[0].cluster_id);
        setViewState({
          longitude: Number(data.hotspots[0].centroid_lon),
          latitude: Number(data.hotspots[0].centroid_lat),
          zoom: 13,
          pitch: 45,
          bearing: 0
        });
      }
    });
  }, []);

  const selectedCluster = useMemo(() => {
    if (!operations || selectedClusterId === null) return null;
    return operations.clusters[String(selectedClusterId)] || null;
  }, [operations, selectedClusterId]);

  const layers = useMemo(() => {
    if (!operations) return [];
    
    const h3Data = operations.hotspots.map(cluster => ({
      hex: cluster.h3_res9 || cluster.h3_res8,
      risk: hourlyRisk(cluster, replayHour),
      clusterId: cluster.cluster_id
    })).filter(d => d.hex);

    const routesData = showRoutes ? operations.routes.map(r => ({
      path: r.geojson?.coordinates || [],
      color: [20, 92, 140]
    })) : [];

    return [
      new H3HexagonLayer({
        id: 'h3-hexagon-layer',
        data: h3Data,
        pickable: true,
        wireframe: false,
        filled: true,
        extruded: true,
        elevationScale: 20,
        getHexagon: (d: any) => d.hex,
        getFillColor: (d: any) => {
          const colorHex = riskColor(d.risk);
          // simple hex to rgb
          const r = parseInt(colorHex.slice(1, 3), 16);
          const g = parseInt(colorHex.slice(3, 5), 16);
          const b = parseInt(colorHex.slice(5, 7), 16);
          return [r, g, b, 200];
        },
        getElevation: (d: any) => d.risk * 10,
        onClick: (info: any) => {
          if (info.object) {
            setSelectedClusterId(info.object.clusterId);
          }
        }
      }),
      new PathLayer({
        id: 'path-layer',
        data: routesData,
        pickable: true,
        widthScale: 20,
        widthMinPixels: 2,
        getPath: (d: any) => d.path,
        getColor: (d: any) => d.color,
        getWidth: () => 1
      })
    ];
  }, [operations, replayHour, showRoutes]);

  if (!operations) return <div className="notice">Loading 3D Geospatial View...</div>;

  return (
    <div className="map-layout" style={{ height: "calc(100vh - 80px)", display: "flex", flexDirection: "column" }}>
      <section className="map-toolbar">
        <div>
          <span className="eyebrow">Geospatial command</span>
          <h1>3D Deck.gl Map View</h1>
        </div>
        <div className="map-controls">
          <label>
            Replay hour
            <input type="range" min={0} max={23} value={replayHour} onChange={(e) => setReplayHour(Number(e.target.value))} />
            <strong>{padHour(replayHour)}</strong>
          </label>
          <button className={showRoutes ? "active" : ""} onClick={() => setShowRoutes(!showRoutes)}>Routes</button>
        </div>
      </section>

      <div style={{ flex: 1, position: "relative" }}>
        <DeckGL
          viewState={viewState}
          onViewStateChange={(e) => setViewState(e.viewState as any)}
          controller={true}
          layers={layers}
          getTooltip={({object}) => object && `Cluster ID: ${object.clusterId}`}
        >
          <Map mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json" />
        </DeckGL>
        
        {/* Simple overlay for selected cluster details */}
        {selectedCluster && (
          <div style={{ position: "absolute", top: 20, right: 20, background: "rgba(16,34,50,0.9)", padding: 20, borderRadius: 8, color: "white", width: 300, zIndex: 10 }}>
            <h3>Cluster {selectedCluster.cluster_id}</h3>
            <p>Risk: {Math.round(selectedCluster.final_risk_0_100)}/100</p>
            <p>Station: {selectedCluster.police_station}</p>
            <p>Records: {selectedCluster.total_violations}</p>
          </div>
        )}
      </div>
    </div>
  );
}
