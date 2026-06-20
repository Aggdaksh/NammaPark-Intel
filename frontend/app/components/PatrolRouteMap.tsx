"use client";

import type { PatrolRoute } from "@/types/api";

export function PatrolRouteMap({ routes }: { routes: PatrolRoute[] }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Patrol routes</span>
          <h2>Dispatch assignments</h2>
        </div>
        <span className="badge">{routes.length}</span>
      </div>
      <div className="route-list">
        {routes.slice(0, 3).map((route) => (
          <article className="route-item" key={route.route_id}>
            <div>
              <strong>{route.unit_id}</strong>
              <span>{route.origin_station}</span>
            </div>
            <ol>
              {route.waypoints.slice(0, 4).map((waypoint) => (
                <li key={`${route.route_id}-${waypoint.cluster_id}`}>
                  Cluster {waypoint.cluster_id}
                  <span>{waypoint.arrival_label}</span>
                </li>
              ))}
            </ol>
          </article>
        ))}
        {!routes.length ? <div className="empty-state">No route output is available.</div> : null}
      </div>
    </section>
  );
}
