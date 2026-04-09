"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const PAGE_SIZE = 25;

type AdminStatus = "New" | "In Progress" | "Resolved" | "Archived";

const ADMIN_STATUSES: AdminStatus[] = [
  "New",
  "In Progress",
  "Resolved",
  "Archived",
];

const CATEGORIES = [
  "Compensation",
  "Interpersonal",
  "Workload",
  "Career",
  "Policy",
  "Environment",
  "Other",
];

const LANG_OPTIONS = [
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
];

interface Proposal {
  id: string;
  department: string | null;
  category: string | null;
  severity: number;
  feedback: number;
  summary: string | null;
  user_name: string | null;
  user_email: string | null;
  admin_status: AdminStatus;
  is_submitted: boolean;
  created_at: string;
}

interface ProposalDetail extends Proposal {
  proposal: string | null;
}

const STATUS_COLORS: Record<AdminStatus, string> = {
  New: "bg-blue-500/20 text-blue-300",
  "In Progress": "bg-yellow-500/20 text-yellow-300",
  Resolved: "bg-green-500/20 text-green-300",
  Archived: "bg-zinc-600/40 text-zinc-400",
};

function severityBadge(n: number) {
  if (n >= 4) return "bg-red-500/20 text-red-300";
  if (n >= 2) return "bg-yellow-500/20 text-yellow-300";
  return "bg-zinc-700 text-zinc-300";
}

function FeedbackBadge({ value }: { value: number }) {
  if (value === 1)
    return (
      <span title="Helpful" className="text-base leading-none text-green-400">
        👍
      </span>
    );
  if (value === -1)
    return (
      <span
        title="Not helpful"
        className="text-base leading-none text-red-400"
      >
        👎
      </span>
    );
  return <span className="text-zinc-600">—</span>;
}

function offsetDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterDept, setFilterDept] = useState<string>("");
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [filterSeverity, setFilterSeverity] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [filterDateFrom, setFilterDateFrom] = useState<string>(() => offsetDate(-30));
  const [filterDateTo, setFilterDateTo] = useState<string>(() => offsetDate(0));

  // Pagination
  const [page, setPage] = useState(1);

  // Detail panel
  const [selected, setSelected] = useState<ProposalDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState(false);

  // AI Analysis
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [analyzeLang, setAnalyzeLang] = useState<string>("en");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<string | null>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [analyzeMeta, setAnalyzeMeta] = useState<{
    count: number;
    lang: string;
    runAt: string;
  } | null>(null);

  const token = () => localStorage.getItem("admin_token") ?? "";

  const fetchProposals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/admin/proposals`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (!res.ok) {
        setError(`Failed to load proposals (${res.status}).`);
        return;
      }
      setProposals((await res.json()) as Proposal[]);
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const fetchDepts = async () => {
      try {
        const res = await fetch(`${API_URL}/departments`);
        if (res.ok) {
          const list = (await res.json()) as { id: string; name: string }[];
          setDepartments(list.map((d) => d.name));
        }
      } catch {
        // non-critical
      }
    };
    void fetchDepts();
  }, []);

  useEffect(() => {
    void fetchProposals();
  }, [fetchProposals]);

  // Reset to page 1 whenever filters change
  const resetPage = () => setPage(1);

  const DATE_PRESETS = [
    { label: "All time", days: null },
    { label: "7 days", days: 7 },
    { label: "30 days", days: 30 },
    { label: "90 days", days: 90 },
  ] as const;

  const applyPreset = (days: number | null) => {
    if (days === null) {
      setFilterDateFrom("");
      setFilterDateTo("");
    } else {
      setFilterDateFrom(offsetDate(-days));
      setFilterDateTo(offsetDate(0));
    }
    resetPage();
  };

  // Client-side filtering (full list)
  const filtered = useMemo(() => {
    return proposals.filter((p) => {
      if (filterDept && p.department !== filterDept) return false;
      if (filterCategory && p.category !== filterCategory) return false;
      if (filterSeverity !== "" && String(p.severity) !== filterSeverity)
        return false;
      if (filterStatus && p.admin_status !== filterStatus) return false;
      if (filterDateFrom && p.created_at.slice(0, 10) < filterDateFrom)
        return false;
      if (filterDateTo && p.created_at.slice(0, 10) > filterDateTo)
        return false;
      return true;
    });
  }, [
    proposals,
    filterDept,
    filterCategory,
    filterSeverity,
    filterStatus,
    filterDateFrom,
    filterDateTo,
  ]);

  // Pagination over filtered list
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageSlice = filtered.slice(
    (safePage - 1) * PAGE_SIZE,
    safePage * PAGE_SIZE
  );
  const pageIds = pageSlice.map((p) => p.id);
  const allOnPageSelected =
    pageIds.length > 0 && pageIds.every((id) => checkedIds.has(id));
  const someOnPageSelected =
    pageIds.length > 0 && pageIds.some((id) => checkedIds.has(id));

  const hasFilters =
    !!filterDept ||
    !!filterCategory ||
    filterSeverity !== "" ||
    !!filterStatus ||
    !!filterDateFrom ||
    !!filterDateTo;

  const clearFilters = () => {
    setFilterDept("");
    setFilterCategory("");
    setFilterSeverity("");
    setFilterStatus("");
    setFilterDateFrom("");
    setFilterDateTo("");
    setPage(1);
  };

  const activeDatePreset =
    !filterDateFrom && !filterDateTo
      ? null
      : DATE_PRESETS.find(
          (p) =>
            p.days !== null &&
            filterDateFrom === offsetDate(-p.days) &&
            filterDateTo === offsetDate(0)
        )?.days ?? "custom";

  const openDetail = async (id: string) => {
    setDetailLoading(true);
    setSelected(null);
    try {
      const res = await fetch(`${API_URL}/admin/proposals/${id}`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (res.ok) setSelected((await res.json()) as ProposalDetail);
    } finally {
      setDetailLoading(false);
    }
  };

  const updateStatus = async (id: string, status: AdminStatus) => {
    setStatusUpdating(true);
    try {
      const res = await fetch(`${API_URL}/admin/proposals/${id}/status`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token()}`,
        },
        body: JSON.stringify({ admin_status: status }),
      });
      if (res.ok) {
        setProposals((prev) =>
          prev.map((p) => (p.id === id ? { ...p, admin_status: status } : p))
        );
        if (selected?.id === id)
          setSelected({ ...selected, admin_status: status });
      }
    } finally {
      setStatusUpdating(false);
    }
  };

  const toggleCheck = (id: string) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleCheckAllOnPage = () => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const runAnalysis = async () => {
    if (checkedIds.size === 0) return;
    setAnalyzing(true);
    setAnalyzeResult(null);
    setAnalyzeError(null);
    setAnalyzeMeta(null);
    try {
      const res = await fetch(`${API_URL}/admin/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token()}`,
        },
        body: JSON.stringify({
          proposal_ids: Array.from(checkedIds),
          language: analyzeLang,
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          detail?: string;
        };
        setAnalyzeError(body.detail ?? `Error ${res.status}`);
        return;
      }
      const result = (await res.json()) as { draft: string };
      setAnalyzeResult(result.draft);
      setAnalyzeMeta({
        count: checkedIds.size,
        lang: LANG_OPTIONS.find((o) => o.value === analyzeLang)?.label ?? analyzeLang,
        runAt: new Date().toLocaleString(),
      });
    } catch {
      setAnalyzeError("Network error.");
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="flex h-full gap-0">
      {/* ── Left: main content ──────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto p-8">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-white">Proposals</h1>
            <p className="text-sm text-zinc-400">
              Submitted improvement proposals. Click a row to view details.
            </p>
          </div>
          <button
            onClick={() => void fetchProposals()}
            className="rounded border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800"
          >
            Refresh
          </button>
        </div>

        {/* ── AI Analysis section ─────────────────────────────────── */}
        <section className="rounded-lg border border-zinc-800 p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">
                AI Analysis
              </h2>
              <p className="text-xs text-zinc-500">
                Select proposals using the checkboxes below, then generate a
                strategic policy draft.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={analyzeLang}
                onChange={(e) => setAnalyzeLang(e.target.value)}
                className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
              >
                {LANG_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <button
                onClick={() => void runAnalysis()}
                disabled={analyzing || checkedIds.size === 0}
                className="rounded border border-purple-600 bg-purple-600/20 px-4 py-1.5 text-sm text-purple-300 transition hover:bg-purple-600/30 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {analyzing
                  ? "Analyzing…"
                  : `Analyze Selected (${checkedIds.size})`}
              </button>
            </div>
          </div>

          {/* Result / placeholder area */}
          {analyzeError && (
            <p className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {analyzeError}
            </p>
          )}

          {analyzeResult && analyzeMeta && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs text-zinc-500">
                  {analyzeMeta.count} proposals · {analyzeMeta.lang} ·{" "}
                  {analyzeMeta.runAt}
                </p>
                <button
                  onClick={() => {
                    setAnalyzeResult(null);
                    setAnalyzeError(null);
                    setAnalyzeMeta(null);
                  }}
                  className="rounded border border-zinc-600 bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-200 transition hover:bg-zinc-700"
                >
                  Clear Result
                </button>
              </div>
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
                {analyzeResult}
              </div>
            </div>
          )}

          {!analyzeResult && !analyzeError && !analyzing && (
            <p className="text-sm text-zinc-600">
              No analysis run yet. Select proposals and click &quot;Analyze
              Selected&quot;.
            </p>
          )}

          {analyzing && (
            <p className="text-sm text-zinc-400">Generating draft…</p>
          )}
        </section>

        {/* ── Filters ─────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Department</label>
            <select
              value={filterDept}
              onChange={(e) => { setFilterDept(e.target.value); resetPage(); }}
              className="rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 focus:outline-none"
            >
              <option value="">All</option>
              {departments.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Category</label>
            <select
              value={filterCategory}
              onChange={(e) => { setFilterCategory(e.target.value); resetPage(); }}
              className="rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 focus:outline-none"
            >
              <option value="">All</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Severity</label>
            <select
              value={filterSeverity}
              onChange={(e) => { setFilterSeverity(e.target.value); resetPage(); }}
              className="rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 focus:outline-none"
            >
              <option value="">All</option>
              {[0, 1, 2, 3, 4, 5].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Status</label>
            <select
              value={filterStatus}
              onChange={(e) => { setFilterStatus(e.target.value); resetPage(); }}
              className="rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 focus:outline-none"
            >
              <option value="">All</option>
              {ADMIN_STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Period</label>
            <div className="flex gap-1">
              {DATE_PRESETS.map(({ label, days }) => (
                <button
                  key={label}
                  onClick={() => applyPreset(days ?? null)}
                  className={`rounded border px-2 py-1 text-xs transition ${
                    activeDatePreset === days
                      ? "border-zinc-400 bg-zinc-700 text-white"
                      : "border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Custom range</label>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={filterDateFrom}
                onChange={(e) => { setFilterDateFrom(e.target.value); resetPage(); }}
                className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
              />
              <span className="text-xs text-zinc-500">–</span>
              <input
                type="date"
                value={filterDateTo}
                onChange={(e) => { setFilterDateTo(e.target.value); resetPage(); }}
                className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
              />
            </div>
          </div>

          {hasFilters && (
            <div className="flex items-end gap-3">
              <button
                onClick={clearFilters}
                className="rounded border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
              >
                Clear filters
              </button>
              <span className="pb-1.5 text-xs text-zinc-500">
                {filtered.length} / {proposals.length} shown
              </span>
            </div>
          )}
        </div>

        {/* ── Table ───────────────────────────────────────────────── */}
        {loading && (
          <p className="text-sm text-zinc-400">Loading proposals…</p>
        )}
        {error && (
          <p className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
            {error}
          </p>
        )}
        {!loading && !error && filtered.length === 0 && (
          <p className="text-sm text-zinc-500">
            {proposals.length === 0
              ? "No submitted proposals yet."
              : "No proposals match the current filters."}
          </p>
        )}

        {!loading && pageSlice.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-800/60 text-xs uppercase tracking-wider text-zinc-400">
                <tr>
                  <th className="px-3 py-3 text-center">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      aria-label={
                        allOnPageSelected
                          ? "Unselect all rows on this page"
                          : "Select all rows on this page"
                      }
                      title={
                        allOnPageSelected
                          ? "Unselect all rows on this page"
                          : "Select all rows on this page"
                      }
                      ref={(el) => {
                        if (el) el.indeterminate = someOnPageSelected && !allOnPageSelected;
                      }}
                      onChange={toggleCheckAllOnPage}
                      className="h-4 w-4 cursor-pointer rounded border-zinc-600 bg-zinc-800 accent-purple-500"
                    />
                  </th>
                  <th className="px-4 py-3 text-left">Department</th>
                  <th className="px-4 py-3 text-left">Category</th>
                  <th className="px-4 py-3 text-left">Sev.</th>
                  <th className="px-4 py-3 text-left">FB</th>
                  <th className="px-4 py-3 text-left">Summary</th>
                  <th className="px-4 py-3 text-left">Submitted by</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {pageSlice.map((p) => (
                  <tr
                    key={p.id}
                    className={`cursor-pointer hover:bg-zinc-800/40 ${selected?.id === p.id ? "bg-zinc-800/60" : ""}`}
                    onClick={() => void openDetail(p.id)}
                  >
                    <td
                      className="px-3 py-3 text-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={checkedIds.has(p.id)}
                        onChange={() => toggleCheck(p.id)}
                        className="h-4 w-4 cursor-pointer rounded border-zinc-600 bg-zinc-800 accent-purple-500"
                      />
                    </td>
                    <td className="px-4 py-3 text-zinc-300">
                      {p.department ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-zinc-300">
                      {p.category ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${severityBadge(p.severity)}`}
                      >
                        {p.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <FeedbackBadge value={p.feedback} />
                    </td>
                    <td className="max-w-xs px-4 py-3 text-zinc-300">
                      <span className="line-clamp-2">{p.summary ?? "—"}</span>
                    </td>
                    <td className="px-4 py-3 text-zinc-300">
                      {p.user_name
                        ? `${p.user_name}${p.user_email ? ` <${p.user_email}>` : ""}`
                        : "Anonymous"}
                    </td>
                    <td
                      className="px-4 py-3"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <select
                        value={p.admin_status}
                        disabled={statusUpdating}
                        onChange={(e) =>
                          void updateStatus(p.id, e.target.value as AdminStatus)
                        }
                        className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[p.admin_status] ?? "bg-zinc-700 text-zinc-300"} border-0 focus:outline-none`}
                      >
                        {ADMIN_STATUSES.map((s) => (
                          <option key={s} value={s} className="bg-zinc-900">
                            {s}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-zinc-400">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Pagination ──────────────────────────────────────────── */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-zinc-500">
              Page {safePage} of {totalPages} &nbsp;·&nbsp;{" "}
              {filtered.length} results
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(1)}
                disabled={safePage === 1}
                className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800 disabled:opacity-30"
              >
                «
              </button>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={safePage === 1}
                className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800 disabled:opacity-30"
              >
                ‹
              </button>

              {/* Page numbers around current page */}
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter(
                  (n) =>
                    n === 1 ||
                    n === totalPages ||
                    Math.abs(n - safePage) <= 2
                )
                .reduce<(number | "…")[]>((acc, n, idx, arr) => {
                  if (idx > 0 && n - (arr[idx - 1] as number) > 1)
                    acc.push("…");
                  acc.push(n);
                  return acc;
                }, [])
                .map((item, idx) =>
                  item === "…" ? (
                    <span key={`ellipsis-${idx}`} className="px-1 text-zinc-600">
                      …
                    </span>
                  ) : (
                    <button
                      key={item}
                      onClick={() => setPage(item as number)}
                      className={`rounded border px-2.5 py-1 text-xs transition ${
                        safePage === item
                          ? "border-zinc-400 bg-zinc-700 text-white"
                          : "border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                      }`}
                    >
                      {item}
                    </button>
                  )
                )}

              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage === totalPages}
                className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800 disabled:opacity-30"
              >
                ›
              </button>
              <button
                onClick={() => setPage(totalPages)}
                disabled={safePage === totalPages}
                className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800 disabled:opacity-30"
              >
                »
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Right: detail panel ─────────────────────────────────── */}
      {(selected || detailLoading) && (
        <div className="flex w-[420px] shrink-0 flex-col border-l border-zinc-800 bg-zinc-900/50">
          <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-white">
                Proposal Detail
              </h2>
              {selected && (
                <select
                  value={selected.admin_status}
                  disabled={statusUpdating}
                  onChange={(e) =>
                    void updateStatus(selected.id, e.target.value as AdminStatus)
                  }
                  className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[selected.admin_status] ?? "bg-zinc-700 text-zinc-300"} border-0 focus:outline-none`}
                >
                  {ADMIN_STATUSES.map((s) => (
                    <option key={s} value={s} className="bg-zinc-900">
                      {s}
                    </option>
                  ))}
                </select>
              )}
            </div>
            <button
              onClick={() => setSelected(null)}
              className="text-xs text-zinc-500 hover:text-zinc-300"
            >
              ✕ Close
            </button>
          </div>

          {detailLoading && (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-zinc-400">Loading…</p>
            </div>
          )}

          {selected && !detailLoading && (
            <div className="flex flex-col gap-5 overflow-y-auto p-6 text-sm">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                <div>
                  <dt className="text-xs text-zinc-500">Department</dt>
                  <dd className="text-zinc-200">
                    {selected.department ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Category</dt>
                  <dd className="text-zinc-200">{selected.category ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Severity</dt>
                  <dd>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${severityBadge(selected.severity)}`}
                    >
                      {selected.severity}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Feedback</dt>
                  <dd>
                    <FeedbackBadge value={selected.feedback} />
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Submitted by</dt>
                  <dd className="text-zinc-200">
                    {selected.user_name
                      ? `${selected.user_name}${selected.user_email ? ` <${selected.user_email}>` : ""}`
                      : "Anonymous"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Date</dt>
                  <dd className="text-zinc-200">
                    {new Date(selected.created_at).toLocaleString()}
                  </dd>
                </div>
              </dl>

              {selected.summary && (
                <div>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    Executive Summary
                  </h3>
                  <p className="text-zinc-200">{selected.summary}</p>
                </div>
              )}

              {selected.proposal && (
                <div>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    Full Proposal
                  </h3>
                  <div className="whitespace-pre-wrap leading-relaxed text-zinc-200">
                    {selected.proposal}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
