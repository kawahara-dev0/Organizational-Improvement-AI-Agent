"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
  mode?: ResponseMode;
};

type ResponseMode = "personal" | "structural";

type SessionResponse = {
  id: string;
  department?: string | null;
  messages: Message[];
  feedback: number;
};

type Department = {
  id: string;
  name: string;
};

const STORAGE_KEY = "oiagent:consultation_id";

const MODE_LABELS: Record<ResponseMode, string> = {
  personal: "Personal Advice",
  structural: "Structural Perspective",
};

const MODE_DESCRIPTIONS: Record<ResponseMode, string> = {
  personal: "Empathetic, practical guidance for the individual",
  structural: "Root-cause analysis from an organizational viewpoint",
};

export default function Home() {
  const apiBase = useMemo(
    () => process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000",
    [],
  );
  const [consultationId, setConsultationId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>("");
  const [mode, setMode] = useState<ResponseMode>("personal");
  const [feedback, setFeedback] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [department, setDepartment] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${apiBase}/departments`);
        if (res.ok) {
          const data = (await res.json()) as Department[];
          setDepartments(data);
        }
      } catch {
        // departments are optional; silently ignore
      }
    })();

    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (!saved) return;
    void loadSession(saved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll to bottom when messages or error change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, error]);

  async function createSession(): Promise<string> {
    const response = await fetch(`${apiBase}/consultations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ department: department || null }),
    });
    if (!response.ok) {
      throw new Error(`Failed to create session (${response.status})`);
    }
    const data = (await response.json()) as { consultation_id: string };
    return data.consultation_id;
  }

  async function loadSession(id: string): Promise<void> {
    const response = await fetch(`${apiBase}/consultations/${id}`);
    if (!response.ok) {
      window.localStorage.removeItem(STORAGE_KEY);
      setConsultationId("");
      setMessages([]);
      return;
    }
    const data = (await response.json()) as SessionResponse;
    setConsultationId(data.id);
    setMessages(data.messages ?? []);
    setFeedback(data.feedback ?? 0);
    setDepartment(data.department ?? "");
    window.localStorage.setItem(STORAGE_KEY, data.id);
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = input.trim();
    if (!content || loading) return;

    setError("");
    setLoading(true);

    const optimisticUser: Message = { role: "user", content, mode };
    setMessages((prev) => [...prev, optimisticUser]);
    setInput("");

    try {
      let sessionId = consultationId;
      if (!sessionId) {
        sessionId = await createSession();
        setConsultationId(sessionId);
        window.localStorage.setItem(STORAGE_KEY, sessionId);
      }

      const response = await fetch(`${apiBase}/consultations/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, mode }),
      });
      if (!response.ok) {
        let detail = `Chat failed (${response.status})`;
        try {
          const body = (await response.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // ignore parse error
        }
        throw new Error(detail);
      }

      const data = (await response.json()) as { reply: string; mode: ResponseMode };
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply, mode: data.mode },
      ]);
    } catch (e) {
      setMessages((prev) => prev.slice(0, -1));
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Submit on Enter (without Shift); newline on Shift+Enter
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  async function submitFeedback(value: -1 | 1) {
    if (!consultationId) return;
    setFeedback(value);
    setError("");
    try {
      const response = await fetch(
        `${apiBase}/consultations/${consultationId}/feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value }),
        },
      );
      if (!response.ok) {
        throw new Error(`Feedback failed (${response.status})`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    }
  }

  async function handleDepartmentChange(value: string) {
    setDepartment(value);
    if (!consultationId) return;
    try {
      await fetch(`${apiBase}/consultations/${consultationId}/department`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ department: value || null }),
      });
    } catch {
      // best-effort; ignore errors
    }
  }

  function resetSession() {
    setConsultationId("");
    setMessages([]);
    setFeedback(0);
    setError("");
    setDepartment("");
    window.localStorage.removeItem(STORAGE_KEY);
  }

  return (
    <main className="mx-auto flex h-screen w-full max-w-3xl flex-col p-4 md:p-6">
      {/* Header */}
      <h1 className="text-xl font-semibold">Organizational Improvement AI Agent</h1>

      {/* Department selector + New Conversation — same row */}
      <div className="mt-3 flex items-center gap-3">
        {departments.length > 0 && (
          <>
            <label htmlFor="department" className="text-xs text-gray-500 shrink-0">
              Department:
            </label>
            <select
              id="department"
              value={department}
              onChange={(e) => void handleDepartmentChange(e.target.value)}
              className="rounded border border-white/20 bg-zinc-800 px-2 py-1 text-xs text-white focus:border-white/40 focus:outline-none"
            >
              <option value="">— Select —</option>
              {departments.map((d) => (
                <option key={d.id} value={d.name}>
                  {d.name}
                </option>
              ))}
            </select>
          </>
        )}
        <button
          type="button"
          onClick={resetSession}
          className="ml-auto rounded border border-white/20 px-3 py-1 text-xs text-gray-500 hover:border-white/40 hover:text-white/60"
        >
          New Conversation
        </button>
      </div>

      {/* Chat history — scrollable, fills remaining height */}
      <section
        ref={scrollRef}
        className="mt-4 flex-1 space-y-3 overflow-y-auto rounded border border-white/10 p-3"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-gray-500">
            Send a message to start the conversation. History will appear here.
          </p>
        ) : (
          messages.map((m, i) => (
            <div
              key={`${m.role}-${i}`}
              className={`rounded p-3 text-sm whitespace-pre-wrap text-white ${
                m.role === "user"
                  ? "ml-8 bg-zinc-800"
                  : "mr-8 bg-[#0a0a0a]"
              }`}
            >
              {/* Mode badge — assistant messages only */}
              {m.role === "assistant" && m.mode && (
                <div className="mb-1">
                  <span className={`rounded border px-1.5 py-0.5 text-xs ${
                    m.mode === "personal"
                      ? "border-blue-500/50 text-blue-400"
                      : "border-purple-500/50 text-purple-400"
                  }`}>
                    {MODE_LABELS[m.mode]}
                  </span>
                </div>
              )}
              {m.content}
            </div>
          ))
        )}
        {/* Loading spinner while waiting for assistant response */}
        {loading && (
          <div className="mr-8 flex items-center gap-2 rounded bg-[#0a0a0a] p-3">
            <svg
              className="h-4 w-4 animate-spin text-white/50"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
              />
            </svg>
            <span className="text-sm text-white/40">Thinking…</span>
          </div>
        )}
        {/* Error message — inline in chat area, not saved to messages */}
        {error && (
          <div className="mr-8 rounded border border-red-500/30 bg-red-900/20 p-3 text-sm text-red-400">
            {error}
          </div>
        )}
      </section>

      {/* Feedback — always reserve space below history */}
      <div className={`mt-2 flex items-center gap-2 text-sm ${consultationId ? "visible" : "invisible"}`}>
        <span className="text-gray-500">Was this response helpful?</span>
        <button
          type="button"
          onClick={() => void submitFeedback(1)}
          className={`rounded border border-white/20 px-2 py-1 transition-colors ${feedback === 1 ? "bg-green-900/40 border-green-500/50 text-green-400" : "text-white/50 hover:text-white/80"}`}
        >
          👍
        </button>
        <button
          type="button"
          onClick={() => void submitFeedback(-1)}
          className={`rounded border border-white/20 px-2 py-1 transition-colors ${feedback === -1 ? "bg-red-900/40 border-red-500/50 text-red-400" : "text-white/50 hover:text-white/80"}`}
        >
          👎
        </button>
      </div>

      {/* Mode selector — above input */}
      <div className="mt-3 flex gap-2">
        {(["personal", "structural"] as ResponseMode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            title={MODE_DESCRIPTIONS[m]}
            className={`flex-1 rounded border-2 px-3 py-1.5 text-sm font-medium transition-colors bg-[#0a0a0a] ${
              mode === m
                ? m === "personal"
                  ? "border-blue-500 text-blue-400"
                  : "border-purple-500 text-purple-400"
                : "border-white/20 text-white/40 hover:border-white/40 hover:text-white/60"
            }`}
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>

      {/* Input area */}
      <form onSubmit={sendMessage} className="mt-2 flex items-end gap-2">
        <textarea
          className="flex-1 resize-none rounded border border-white/20 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-white/40 focus:outline-none"
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            mode === "personal"
              ? "Describe your workplace concern… (Enter to send, Shift+Enter for new line)"
              : "Describe an organizational or structural issue… (Enter to send, Shift+Enter for new line)"
          }
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || input.trim().length === 0}
          className="rounded border border-white/20 bg-[#0a0a0a] px-4 py-2 text-sm text-white transition-colors hover:border-white/40 disabled:opacity-40"
        >
          {loading ? "…" : "Send"}
        </button>
      </form>

    </main>
  );
}
