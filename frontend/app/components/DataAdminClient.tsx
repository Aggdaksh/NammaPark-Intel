"use client";

import { useEffect, useState } from "react";
import { loadSession } from "@/lib/api";
import type { Session } from "@/types/api";
import { CsvUploader } from "./CsvUploader";

type PipelineStatus = {
  status?: string;
  current_step?: string;
  message?: string;
  error?: string;
  version?: string;
  pid?: number;
  csv?: string;
};

export function DataAdminClient() {
  const [session, setSession] = useState<Session | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);

  useEffect(() => {
    loadSession().then(setSession).catch(() => null);
    refreshStatus().catch(() => null);
  }, []);

  async function refreshStatus() {
    const response = await fetch("/api/pipeline", { cache: "no-store" });
    const payload = await response.json();
    setPipeline(payload);
  }

  if (session && session.role !== "admin") {
    return (
      <section className="panel">
        <span className="eyebrow">Restricted</span>
        <h1>Administrator access required</h1>
        <p className="panel-note">Data ingestion and model runs are available only for administrator accounts.</p>
      </section>
    );
  }

  return (
    <div className="data-admin-layout">
      <section className="brief-panel data-hero">
        <div>
          <span className="eyebrow">Data administration</span>
          <h1>Ingestion and model operations</h1>
          <p>
            Upload violation CSV files, start a backend pipeline run, and track the active model export used by the dashboard.
          </p>
        </div>
        <div className="brief-kpis">
          <div>
            <span>Access level</span>
            <strong>{session?.role || "checking"}</strong>
          </div>
          <div>
            <span>Pipeline</span>
            <strong>{pipeline?.status || "idle"}</strong>
          </div>
        </div>
        <div className="brief-actions">
          <button type="button" className="primary-button" onClick={refreshStatus}>
            Refresh status
          </button>
        </div>
      </section>

      <CsvUploader />

      <div className="data-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Pipeline status</span>
              <h2>Current job</h2>
            </div>
            <span className="badge">{pipeline?.status || "--"}</span>
          </div>
          <div className="detail-grid">
            <div>
              <span>Step</span>
              <strong>{pipeline?.current_step || "--"}</strong>
            </div>
            <div>
              <span>Version</span>
              <strong>{pipeline?.version || "--"}</strong>
            </div>
            <div>
              <span>Process</span>
              <strong>{pipeline?.pid || "--"}</strong>
            </div>
            <div>
              <span>Source</span>
              <strong>{pipeline?.csv ? "Uploaded CSV" : "Fallback artifacts"}</strong>
            </div>
          </div>
          <p className={pipeline?.error ? "upload-status error" : "panel-note"}>
            {pipeline?.error || pipeline?.message || "No active pipeline job has been started."}
          </p>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Deployment note</span>
              <h2>Render worker required</h2>
            </div>
          </div>
          <p className="panel-note">
            On Vercel, this page must use a Render FastAPI backend through <strong>NAMMAPARK_PIPELINE_URL</strong>. Long Python
            model runs should execute on Render, not inside Vercel serverless functions.
          </p>
        </section>
      </div>
    </div>
  );
}
