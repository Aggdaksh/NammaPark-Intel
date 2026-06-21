"use client";

import { FormEvent, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";

export function LoginClient() {
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("gridlock");
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setStatus(null);
    try {
      await apiFetch("/api/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      window.location.assign(searchParams.get("next") || "/");
    } catch {
      setStatus("Login failed. Please verify the authorized operator credentials.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-agency">Bengaluru Traffic Police</div>
        <img className="login-logo" src="/assets/nammapark-wordmark.png" alt="NammaPark Intel" />
        <h1 id="login-title">Operator Login</h1>
        <p>Secure sign-in for authorized parking enforcement operations personnel.</p>
        <form onSubmit={handleSubmit} className="login-form">
          <label>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button type="submit" disabled={submitting}>
            {submitting ? "Signing in" : "Login"}
          </button>
          {status ? <div className="form-status" role="alert">{status}</div> : null}
        </form>
        <div className="login-footer">
          <span>Authorized local operator</span>
          <strong>{username || "operator"}</strong>
        </div>
      </section>
    </main>
  );
}
