"use client";

import { useState } from "react";

export function CsvUploader() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setStatus("uploading");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }
      
      setStatus("success");
      setMessage("Upload successful! Ingestion running in background.");
      setFile(null);
    } catch (err: any) {
      setStatus("error");
      setMessage(err.message || "Upload failed");
    }
  };

  return (
    <section className="panel upload-panel" style={{ marginTop: "1rem" }}>
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Data Ingestion</span>
          <h2>Upload Violation CSV</h2>
        </div>
      </div>
      <form onSubmit={handleUpload} style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
        <input 
          type="file" 
          accept=".csv" 
          onChange={(e) => setFile(e.target.files?.[0] || null)} 
          disabled={status === "uploading"}
        />
        <button 
          type="submit" 
          className="primary-button" 
          disabled={!file || status === "uploading"}
        >
          {status === "uploading" ? "Uploading..." : "Ingest Data"}
        </button>
      </form>
      {message && (
        <p style={{ marginTop: "0.5rem", color: status === "error" ? "red" : "green" }}>
          {message}
        </p>
      )}
    </section>
  );
}
