import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_UPLOAD_BYTES = 150 * 1024 * 1024;
const REMOTE_PIPELINE_BASE =
  process.env.NAMMAPARK_PIPELINE_URL ||
  process.env.NAMMAPARK_FASTAPI_URL ||
  process.env.FASTAPI_API_BASE_URL ||
  "";
const AUTH_BACKEND_BASE =
  process.env.NAMMAPARK_BACKEND_URL ||
  process.env.BACKEND_API_BASE_URL ||
  "http://127.0.0.1:8788";

async function requireAdmin(request: NextRequest) {
  try {
    const response = await fetch(new URL("/api/session", AUTH_BACKEND_BASE), {
      headers: { cookie: request.headers.get("cookie") || "" },
      cache: "no-store"
    });
    if (!response.ok) return false;
    const session = await response.json();
    return Boolean(session?.authenticated && session?.role === "admin");
  } catch {
    return false;
  }
}

function workspacePath(...segments: string[]) {
  return path.join(process.cwd(), ...segments);
}

function safeFilename(value: string) {
  return value.replace(/[^A-Za-z0-9_. -]+/g, "_").slice(0, 160) || "upload.csv";
}

function pythonBin() {
  const configured = process.env.NAMMAPARK_PYTHON_BIN || process.env.PYTHON_BIN || process.env.PYTHON;
  if (configured) return configured;
  const venvPython = workspacePath(".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python3";
}

async function readStatus() {
  const statusPath = workspacePath("ml", "artifacts", "pipeline_ui_run.json");
  try {
    return JSON.parse(await readFile(statusPath, "utf-8"));
  } catch {
    return {
      status: "idle",
      message: "No uploaded pipeline run has been started yet."
    };
  }
}

export async function GET() {
  if (REMOTE_PIPELINE_BASE) {
    try {
      const response = await fetch(new URL("/api/pipeline", REMOTE_PIPELINE_BASE), { cache: "no-store" });
      const text = await response.text();
      return new NextResponse(text, {
        status: response.status,
        headers: { "content-type": response.headers.get("content-type") || "application/json; charset=utf-8" }
      });
    } catch {
      return NextResponse.json(
        { status: "unavailable", detail: "Configured pipeline backend is not reachable." },
        { status: 503 }
      );
    }
  }
  return NextResponse.json(await readStatus());
}

export async function POST(request: NextRequest) {
  if (!(await requireAdmin(request))) {
    return NextResponse.json(
      { status: "forbidden", detail: "Administrator role is required for data ingestion and model pipeline runs." },
      { status: 403 }
    );
  }
  const formData = await request.formData();
  if (REMOTE_PIPELINE_BASE) {
    try {
      const response = await fetch(new URL("/api/pipeline", REMOTE_PIPELINE_BASE), {
        method: "POST",
        body: formData,
        cache: "no-store"
      });
      const text = await response.text();
      return new NextResponse(text, {
        status: response.status,
        headers: { "content-type": response.headers.get("content-type") || "application/json; charset=utf-8" }
      });
    } catch {
      return NextResponse.json(
        { status: "unavailable", detail: "Pipeline backend is not reachable. Set NAMMAPARK_PIPELINE_URL to the Render FastAPI URL." },
        { status: 503 }
      );
    }
  }
  if (process.env.VERCEL) {
    return NextResponse.json(
      {
        status: "not_configured",
        detail: "Vercel cannot run the local Python ML pipeline. Set NAMMAPARK_PIPELINE_URL or NAMMAPARK_FASTAPI_URL to your Render FastAPI service."
      },
      { status: 501 }
    );
  }

  const file = formData.get("file");
  const runValue = String(formData.get("run") || "false") === "true";
  const maxRowsValue = String(formData.get("maxRows") || "").trim();
  const maxRows = maxRowsValue ? Number(maxRowsValue) : undefined;

  if (!(file instanceof File)) {
    return NextResponse.json({ status: "error", detail: "Attach a CSV file before starting ingestion." }, { status: 400 });
  }
  if (!file.name.toLowerCase().endsWith(".csv")) {
    return NextResponse.json({ status: "error", detail: "Only CSV files are supported." }, { status: 400 });
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ status: "error", detail: "CSV upload is larger than the 150 MB safety limit." }, { status: 413 });
  }
  if (maxRows !== undefined && (!Number.isFinite(maxRows) || maxRows <= 0)) {
    return NextResponse.json({ status: "error", detail: "Max rows must be a positive number." }, { status: 400 });
  }

  const uploadDir = workspacePath("ml", "data", "uploads");
  await mkdir(uploadDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const uploadPath = path.join(uploadDir, `${stamp}-${safeFilename(file.name)}`);
  const bytes = Buffer.from(await file.arrayBuffer());
  await writeFile(uploadPath, bytes);

  const saved = await stat(uploadPath);
  const version = `ui-${Date.now()}`;
  const responsePayload: Record<string, unknown> = {
    status: runValue ? "running" : "uploaded",
    filename: file.name,
    saved_path: uploadPath,
    size_bytes: saved.size,
    model_version: version
  };

  if (!runValue) {
    return NextResponse.json({
      ...responsePayload,
      message: "CSV saved locally. Enable Run model pipeline to train and export refreshed dashboard data."
    });
  }

  const statusPath = workspacePath("ml", "artifacts", "pipeline_ui_run.json");
  const args = [
    workspacePath("tools", "run_uploaded_pipeline.py"),
    "--csv",
    uploadPath,
    "--version",
    version,
    "--status-path",
    statusPath,
    "--use-osm-snap",
    "--graph-path",
    workspacePath("ml", "data", "bengaluru.graphml")
  ];
  if (maxRows) {
    args.push("--max-rows", String(maxRows));
  }

  const child = spawn(pythonBin(), args, {
    cwd: process.cwd(),
    env: process.env,
    detached: true,
    stdio: "ignore"
  });
  child.unref();

  await writeFile(
    statusPath,
    JSON.stringify(
      {
        status: "running",
        current_step: "queued",
        csv: uploadPath,
        version,
        pid: child.pid,
        started_at: new Date().toISOString(),
        message: "Pipeline has started in the background. Keep this app running and refresh status from the dashboard."
      },
      null,
      2
    )
  );

  return NextResponse.json({
    ...responsePayload,
    pid: child.pid,
    message: "Pipeline started. Use the status panel to track ETL, training, and fallback export."
  });
}
