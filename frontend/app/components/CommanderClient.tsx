"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { apiFetch, loadOperationsData } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { OperationsData } from "@/types/api";

type Message = {
  role: "assistant" | "operator";
  content: string;
};

const examples = [
  "Why is cluster 517 risky?",
  "Show active anomaly alerts.",
  "Which patrol route should start first?"
];

export function CommanderClient() {
  const [operations, setOperations] = useState<OperationsData | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Operational context is ready.\n\nYou may request a briefing on priority zones, exception alerts, patrol assignments, or any listed cluster ID."
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    loadOperationsData().then(setOperations).catch(() => null);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function askCommander(message: string) {
    const trimmed = message.trim();
    if (!trimmed || loading) return;
    setInput("");
    setLoading(true);
    setMessages((current) => [...current, { role: "operator", content: trimmed }]);
    try {
      const response = await apiFetch<{ response: string }>("/api/commander", {
        method: "POST",
        body: JSON.stringify({ user_message: trimmed })
      });
      setMessages((current) => [...current, { role: "assistant", content: response.response }]);
    } catch {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: "Unable to retrieve the command briefing. Please verify the local API service and try again."
        }
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void askCommander(input);
  }

  return (
    <div className="commander-layout">
      <section className="commander-panel">
        <div className="commander-header">
          <div>
            <span className="eyebrow">Command assistant</span>
            <h1>Review traffic enforcement intelligence</h1>
          </div>
          <span className="data-pill">Operational data</span>
        </div>
        <div className="context-pills">
          <span>Operational context loaded</span>
          <span>Priority zones, exception alerts, and patrol assignments</span>
        </div>
        <div className="chat-shell" aria-label="Commander chat">
          <div className="chat-log">
            {messages.map((message, index) => (
              <article key={`${message.role}-${index}`} className={`chat-message ${message.role}`}>
                <span>{message.role === "operator" ? "Operator" : "Assistant"}</span>
                <p>{message.content}</p>
              </article>
            ))}
            {loading ? (
              <article className="chat-message assistant">
                <span>Assistant</span>
                <p>Preparing briefing...</p>
              </article>
            ) : null}
            <div ref={bottomRef} />
          </div>
          <div className="example-row">
            {examples.map((example) => (
              <button key={example} type="button" onClick={() => askCommander(example)}>
                {example}
              </button>
            ))}
          </div>
          <form className="chat-form" onSubmit={handleSubmit}>
            <label htmlFor="commanderInput">Message</label>
            <textarea
              id="commanderInput"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask for a briefing on priority zones, alerts, patrol assignments, or a cluster ID..."
              rows={2}
            />
            <button type="submit" disabled={loading || !input.trim()}>
              Submit
            </button>
          </form>
        </div>
      </section>

      <aside className="commander-sidebar">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Priority zones</span>
              <h2>Current list</h2>
            </div>
            <span className="badge">{operations?.hotspots.length || "--"}</span>
          </div>
          <div className="assistant-list">
            {(operations?.hotspots || []).slice(0, 6).map((cluster) => (
              <button key={cluster.cluster_id} type="button" onClick={() => askCommander(`Brief cluster ${cluster.cluster_id}`)}>
                <span>{Math.round(cluster.final_risk_0_100)}</span>
                <strong>Cluster {cluster.cluster_id}</strong>
                <small>{cluster.police_station} - {formatNumber(cluster.predicted_delay_min, 4)} min/vehicle</small>
              </button>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Exception alerts</span>
              <h2>Active alerts</h2>
            </div>
            <span className="badge">{operations?.anomalies.length || "--"}</span>
          </div>
          <div className="assistant-list alerts">
            {(operations?.anomalies || []).slice(0, 4).map((alert) => (
              <button key={alert.cluster_id} type="button" onClick={() => askCommander(`Explain anomaly cluster ${alert.cluster_id}`)}>
                <span>{formatNumber(alert.anomaly_zscore, 2)}</span>
                <strong>Cluster {alert.cluster_id}</strong>
                <small>{alert.police_station} - statistical exception</small>
              </button>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
