"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

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
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Ready. Ask for hotspot priority, anomaly explanation, patrol routing, or a specific cluster briefing."
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

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
      <section className="commander-header">
        <span className="eyebrow">Command assistant</span>
        <h1>Grounded operations briefing</h1>
        <p>
          Responses are grounded in the current hotspot, anomaly, route, and SHAP context exported by the ML pipeline.
        </p>
      </section>
      <section className="chat-shell" aria-label="Commander chat">
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
            placeholder="Ask about a cluster, patrol assignment, or anomaly alert"
            rows={3}
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
