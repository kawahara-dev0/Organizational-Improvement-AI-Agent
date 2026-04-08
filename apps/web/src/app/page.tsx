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
  is_submitted?: boolean;
};

type SubmitDraft = {
  summary: string;
  proposal: string;
};

type Department = {
  id: string;
  name: string;
};

type DraftLanguage = "auto" | "ja" | "en";

const STORAGE_KEY = "oiagent:consultation_id";

const MODE_LABELS: Record<ResponseMode, string> = {
  personal: "Personal Advice",
  structural: "Structural Perspective",
};

const MODE_DESCRIPTIONS: Record<ResponseMode, string> = {
  personal: "Empathetic, practical guidance for the individual",
  structural: "Root-cause analysis from an organizational viewpoint",
};

/** Two-column shell: 80% of viewport (cap 96rem); each pane ~half inside the row. */
const HEADER_SHELL =
  "mx-auto w-full max-w-[min(80%,96rem,calc((100vw-2rem)*0.8))]";

const BODY_SHELL =
  "mx-auto flex min-h-0 w-full max-w-[min(80%,96rem,calc((100vw-2rem)*0.8))] min-w-0 flex-1 flex-col gap-4 overflow-hidden md:flex-row md:items-stretch";

const PANE_TWO = "flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden";

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
  const [isSubmitted, setIsSubmitted] = useState<boolean>(false);
  const [submitDraft, setSubmitDraft] = useState<SubmitDraft | null>(null);
  const [submitName, setSubmitName] = useState<string>("");
  const [submitEmail, setSubmitEmail] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [draftLanguage, setDraftLanguage] = useState<DraftLanguage>("auto");
  const scrollRef = useRef<HTMLDivElement>(null);

  const canCreateDraft =
    messages.length > 0 &&
    !isSubmitted &&
    !loading &&
    !submitting;

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
    setIsSubmitted(data.is_submitted ?? false);
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

  async function requestSubmit() {
    if (submitting || loading || isSubmitted || messages.length === 0) return;
    setError("");
    setSubmitting(true);
    try {
      let sessionId = consultationId;
      if (!sessionId) {
        sessionId = await createSession();
        setConsultationId(sessionId);
        window.localStorage.setItem(STORAGE_KEY, sessionId);
      }
      const response = await fetch(`${apiBase}/consultations/${sessionId}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: draftLanguage }),
      });
      if (!response.ok) {
        let detail = `Draft generation failed (${response.status})`;
        try {
          const body = (await response.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // ignore
        }
        throw new Error(detail);
      }
      const data = (await response.json()) as SubmitDraft;
      setSubmitDraft(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!consultationId || !submitDraft || submitting) return;
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch(
        `${apiBase}/consultations/${consultationId}/submit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            summary: submitDraft.summary,
            proposal: submitDraft.proposal,
            user_name: submitName || null,
            user_email: submitEmail || null,
          }),
        },
      );
      if (!response.ok) {
        let detail = `Submit failed (${response.status})`;
        try {
          const body = (await response.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // ignore
        }
        throw new Error(detail);
      }
      setIsSubmitted(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSubmitting(false);
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
    setIsSubmitted(false);
    setSubmitDraft(null);
    setSubmitName("");
    setSubmitEmail("");
    window.localStorage.removeItem(STORAGE_KEY);
  }

  return (
    <main className="mx-auto box-border flex h-screen w-full min-w-0 flex-col p-4 md:p-6">
      <div className={HEADER_SHELL}>
        <h1 className="text-xl font-semibold">Organizational Improvement AI Agent</h1>

        {/* Top controls: align to left/right panes */}
        <div className="mt-3 flex min-w-0 flex-col gap-3 md:flex-row md:gap-10">
          {/* Left pane controls */}
          <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              {departments.length > 0 && (
                <>
                  <label htmlFor="department" className="shrink-0 text-xs text-gray-500">
                    Department (optional):
                  </label>
                  <select
                    id="department"
                    value={department}
                    onChange={(e) => void handleDepartmentChange(e.target.value)}
                    className="min-w-0 rounded border border-white/20 bg-zinc-800 px-2 py-1 text-xs text-white focus:border-white/40 focus:outline-none"
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
            </div>
            <button
              type="button"
              onClick={resetSession}
              className="shrink-0 rounded border border-white/20 px-3 py-1 text-xs text-gray-500 hover:border-white/40 hover:text-white/60"
            >
              New Conversation
            </button>
          </div>

          {/* Right pane controls */}
          <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => void requestSubmit()}
              disabled={!canCreateDraft}
              className="shrink-0 rounded border border-amber-500/50 bg-amber-900/30 px-3 py-1.5 text-xs font-medium text-amber-200 transition-colors hover:border-amber-400 hover:bg-amber-900/50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? "Creating…" : "Create proposal draft"}
            </button>
            <div className="flex min-w-0 items-center gap-2">
              <label htmlFor="draft-lang" className="shrink-0 text-xs text-gray-400">
                Draft output language
              </label>
              <select
                id="draft-lang"
                value={draftLanguage}
                onChange={(e) => setDraftLanguage(e.target.value as DraftLanguage)}
                disabled={isSubmitted}
                className="min-w-[10rem] rounded border border-white/20 bg-zinc-800 px-2 py-1 text-xs text-white focus:border-white/40 focus:outline-none disabled:opacity-40"
              >
                <option value="auto">Auto (match conversation)</option>
                <option value="ja">日本語</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <div className={`mt-4 ${BODY_SHELL}`}>
        <div className={PANE_TWO}>
          {/* Chat history — scrollable */}
          <section
            ref={scrollRef}
            className="flex-1 space-y-3 overflow-y-auto rounded border border-white/10 p-3"
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
                    m.role === "user" ? "ml-8 bg-zinc-800" : "mr-8 bg-[#0a0a0a]"
                  }`}
                >
                  {/* Mode badge — assistant messages only */}
                  {m.role === "assistant" && m.mode && (
                    <div className="mb-1">
                      <span
                        className={`rounded border px-1.5 py-0.5 text-xs ${
                          m.mode === "personal"
                            ? "border-blue-500/50 text-blue-400"
                            : "border-purple-500/50 text-purple-400"
                        }`}
                      >
                        {MODE_LABELS[m.mode]}
                      </span>
                    </div>
                  )}
                  {m.content}
                </div>
              ))
            )}

            {/* Loading spinner */}
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

            {/* Error message — inline in chat, not saved */}
            {error && (
              <div className="mr-8 rounded border border-red-500/30 bg-red-900/20 p-3 text-sm text-red-400">
                {error}
              </div>
            )}
          </section>

          {/* Feedback + Submit to Manager */}
          <div
            className={`mt-2 flex items-center gap-2 text-sm ${consultationId ? "visible" : "invisible"}`}
          >
            <span className="text-gray-500">Was this response helpful?</span>
            <button
              type="button"
              onClick={() => void submitFeedback(1)}
              className={`rounded border border-white/20 px-2 py-1 transition-colors ${
                feedback === 1
                  ? "border-green-500/50 bg-green-900/40 text-green-400"
                  : "text-white/50 hover:text-white/80"
              }`}
            >
              👍
            </button>
            <button
              type="button"
              onClick={() => void submitFeedback(-1)}
              className={`rounded border border-white/20 px-2 py-1 transition-colors ${
                feedback === -1
                  ? "border-red-500/50 bg-red-900/40 text-red-400"
                  : "text-white/50 hover:text-white/80"
              }`}
            >
              👎
            </button>
          </div>

          {/* Mode selector */}
          <div className="mt-3 flex gap-2">
            {(["personal", "structural"] as ResponseMode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                disabled={isSubmitted}
                title={MODE_DESCRIPTIONS[m]}
                className={`flex-1 rounded border-2 bg-[#0a0a0a] px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
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
              className="flex-1 resize-none rounded border border-white/20 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-white/40 focus:outline-none disabled:cursor-not-allowed disabled:opacity-40"
              rows={3}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isSubmitted
                  ? "This conversation has been submitted."
                  : mode === "personal"
                    ? "Describe your workplace concern… (Enter to send, Shift+Enter for new line)"
                    : "Describe an organizational or structural issue… (Enter to send, Shift+Enter for new line)"
              }
              disabled={loading || submitting || isSubmitted}
            />
            <button
              type="submit"
              disabled={loading || submitting || isSubmitted || input.trim().length === 0}
              className="rounded border border-white/20 bg-[#0a0a0a] px-4 py-2 text-sm text-white transition-colors hover:border-white/40 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? "…" : "Send"}
            </button>
          </form>
        </div>

        <div
          className={`${PANE_TWO} rounded border border-amber-500/30 bg-amber-900/10 max-h-[50vh] md:max-h-none`}
        >
          {!submitDraft ? (
            <div className="flex flex-1 items-center justify-center p-6 text-center text-sm leading-relaxed text-gray-400">
              When you are ready to report to your manager, select the &quot;Create proposal
              draft&quot; button.
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 border-b border-amber-500/20 px-4 py-3">
                <p className="text-xs font-semibold text-amber-400">
                  Review your proposal draft
                </p>
                {isSubmitted && (
                  <span className="rounded border border-green-500/50 px-1.5 py-0.5 text-xs text-green-400">
                    Submitted
                  </span>
                )}
              </div>

              {/* Scrollable content */}
              <div className="flex flex-1 flex-col overflow-y-auto p-4 text-sm">
                <div className="space-y-4">
                  <div>
                    <p className="mb-1 text-xs text-gray-400">Executive Summary</p>
                    <p className="whitespace-pre-wrap text-white/80">{submitDraft.summary}</p>
                  </div>
                  <div>
                    <p className="mb-1 text-xs text-gray-400">Full Proposal</p>
                    <p className="whitespace-pre-wrap text-white/80">{submitDraft.proposal}</p>
                  </div>
                </div>
              </div>

              {/* Fixed footer (always accessible) */}
              <div className="border-t border-amber-500/20 p-4">
                {isSubmitted ? (
                  <p className="mx-auto w-full text-center text-sm text-green-300">
                    Thank you for your submission. We will carefully review the content.
                    <br />
                    If you would like to start a new conversation, please select &quot;New
                    Conversation&quot;.
                  </p>
                ) : (
                  <div className="flex w-full flex-col items-center">
                    <p className="w-full text-center text-xs text-gray-400">
                      Contact info is optional. If provided, managers may reach out for follow-up.
                    </p>
                    <form
                      onSubmit={(e) => void confirmSubmit(e)}
                      className="mt-2 w-full max-w-sm space-y-2"
                    >
                      <input
                        type="text"
                        placeholder="Name (optional)"
                        value={submitName}
                        onChange={(e) => setSubmitName(e.target.value)}
                        className="w-full rounded border border-white/20 bg-zinc-800 px-2 py-1 text-xs text-white placeholder-white/30 focus:border-white/40 focus:outline-none"
                      />
                      <input
                        type="email"
                        placeholder="Email (optional)"
                        value={submitEmail}
                        onChange={(e) => setSubmitEmail(e.target.value)}
                        className="w-full rounded border border-white/20 bg-zinc-800 px-2 py-1 text-xs text-white placeholder-white/30 focus:border-white/40 focus:outline-none"
                      />
                      <button
                        type="submit"
                        disabled={submitting}
                        className="w-full rounded border border-amber-500/50 bg-amber-900/20 px-4 py-1.5 text-xs text-amber-300 transition-colors hover:bg-amber-900/40 disabled:opacity-40"
                      >
                        {submitting ? "Submitting…" : "Send to Manager"}
                      </button>
                    </form>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
