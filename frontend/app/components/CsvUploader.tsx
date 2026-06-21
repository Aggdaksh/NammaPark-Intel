"use client";

import { useState } from "react";

type PipelineStatus = {
  status?: string;
  current_step?: string;
  message?: string;
  error?: string;
  version?: string;
  csv?: string;
  steps?: Array<{ name: string; status: string }>;
};

export function CsvUploader() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");
  const [runPipeline, setRunPipeline] = useState(false);
  const [maxRows, setMaxRows] = useState("");
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);

  async function refreshPipelineStatus() {
    const res = await fetch("/api/pipeline", { cache: "no-store" });
    const payload = await res.json();
    setPipelineStatus(payload);
  }

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setStatus("uploading");
    const formData = new FormData();
    formData.append("file", file);
    formData.append("run", String(runPipeline));
    if (maxRows.trim()) formData.append("maxRows", maxRows.trim());

    try {
      const res = await fetch("/api/pipeline", {
        method: "POST",
        body: formData,
      });

      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(payload?.detail || payload?.message || "Upload failed");
      }
      
      setStatus("success");
      setMessage(
        runPipeline
          ? `CSV saved and model pipeline started as ${payload?.model_version}.`
          : `CSV saved locally at ${payload?.saved_path}.`
      );
      setPipelineStatus(payload);
      setFile(null);
    } catch (err: any) {
      setStatus("error");
      setMessage(err.message || "Upload failed");
    }
  };

  return (
    <section className="panel upload-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Data Ingestion</span>
          <h2>Upload CSV and run pipeline</h2>
        </div>
        <button type="button" onClick={refreshPipelineStatus}>Status</button>
      </div>
      <form onSubmit={handleUpload} className="upload-form">
        <input 
          type="file" 
          accept=".csv" 
          onChange={(e) => setFile(e.target.files?.[0] || null)} 
          disabled={status === "uploading"}
        />
        <label className="upload-option">
          <span>Max rows</span>
          <input
            type="number"
            min="1"
            inputMode="numeric"
            value={maxRows}
            onChange={(event) => setMaxRows(event.target.value)}
            placeholder="Full file"
            disabled={status === "uploading"}
          />
        </label>
        <label className="upload-toggle">
          <input
            type="checkbox"
            checked={runPipeline}
            onChange={(event) => setRunPipeline(event.target.checked)}
            disabled={status === "uploading"}
          />
          <span>Run model pipeline after upload</span>
        </label>
        <button 
          type="submit" 
          className="primary-button" 
          disabled={!file || status === "uploading"}
        >
          {status === "uploading" ? "Uploading..." : runPipeline ? "Upload and run model" : "Upload CSV"}
        </button>
      </form>
      {message && (
        <p className={status === "error" ? "upload-status error" : "upload-status success"}>
          {message}
        </p>
      )}
      {pipelineStatus ? (
        <div className="pipeline-status">
          <div>
            <span>Status</span>
            <strong>{pipelineStatus.status || "unknown"}</strong>
          </div>
          <div>
            <span>Step</span>
            <strong>{pipelineStatus.current_step || "--"}</strong>
          </div>
          <div>
            <span>Version</span>
            <strong>{pipelineStatus.version || "--"}</strong>
          </div>
          <p>{pipelineStatus.error || pipelineStatus.message || "Refresh status while the pipeline is running."}</p>
        </div>
      ) : null}
      <p className="upload-hint">
        Full retraining can take time on large CSV files. Use Max rows for a quick smoke run, or leave it blank for a full local run.
      </p>
    </section>
  );
}
