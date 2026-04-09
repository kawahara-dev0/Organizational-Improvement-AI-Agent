"use client";

import { useCallback, useEffect, useState } from "react";

const LANG_OPTIONS = [
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const CATEGORIES = [
  "Compensation",
  "Interpersonal",
  "Workload",
  "Career",
  "Policy",
  "Environment",
  "Other",
  "Unknown",
];

const SEVERITY_COLORS: Record<number, string> = {
  0: "bg-zinc-800 text-zinc-400",
  1: "bg-blue-900/50 text-blue-300",
  2: "bg-yellow-900/50 text-yellow-300",
  3: "bg-orange-900/50 text-orange-300",
  4: "bg-red-900/60 text-red-300",
  5: "bg-red-700/70 text-red-200 font-semibold",
};

interface HeatmapCell {
  category: string;
  severity: number;
  count: number;
}

interface DeptRow {
  department: string;
  consultation_count: number;
  submitted_count: number;
  avg_severity: number;
}

interface TrendsData {
  heatmap: HeatmapCell[];
  by_department: DeptRow[];
}


// Returns an ISO date string (YYYY-MM-DD) offset from today by `days`
function offsetDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function TrendsPage() {
  const [data, setData] = useState<TrendsData | null>(null);
  const [departments, setDepartments] = useState<string[]>([]);
  const [selectedDept, setSelectedDept] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>(() => offsetDate(-30));
  const [dateTo, setDateTo] = useState<string>(() => offsetDate(0));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryLang, setSummaryLang] = useState<string>("en");

  const token = () => localStorage.getItem("admin_token") ?? "";

  const buildQuery = useCallback(
    (dept: string, from: string, to: string) => {
      const params = new URLSearchParams();
      if (dept) params.set("department", dept);
      if (from) params.set("date_from", from);
      if (to) params.set("date_to", to);
      const qs = params.toString();
      return `${API_URL}/admin/trends${qs ? `?${qs}` : ""}`;
    },
    []
  );

  const fetchTrends = useCallback(
    async (dept: string, from: string, to: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(buildQuery(dept, from, to), {
          headers: { Authorization: `Bearer ${token()}` },
        });
        if (!res.ok) {
          setError(`Failed to load trends (${res.status}).`);
          return;
        }
        setData((await res.json()) as TrendsData);
      } catch {
        setError("Network error.");
      } finally {
        setLoading(false);
      }
    },
    [buildQuery]
  );

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
    void fetchTrends(selectedDept, dateFrom, dateTo);
  }, [selectedDept, dateFrom, dateTo, fetchTrends]);

  const applyPreset = (days: number | null) => {
    if (days === null) {
      setDateFrom("");
      setDateTo("");
    } else {
      setDateFrom(offsetDate(-days));
      setDateTo(offsetDate(0));
    }
  };

  const generateSummary = async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    setSummary(null);
    try {
      const res = await fetch(`${API_URL}/admin/trends/summary`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token()}`,
        },
        body: JSON.stringify({
          department: selectedDept || null,
          date_from: dateFrom || null,
          date_to: dateTo || null,
          language: summaryLang,
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        setSummaryError(body.detail ?? `Error ${res.status}`);
        return;
      }
      const result = (await res.json()) as { summary: string };
      setSummary(result.summary);
    } catch {
      setSummaryError("Network error.");
    } finally {
      setSummaryLoading(false);
    }
  };

  // Build heatmap lookup: category → severity → count
  const heatmapMap: Record<string, Record<number, number>> = {};
  for (const cell of data?.heatmap ?? []) {
    if (!heatmapMap[cell.category]) heatmapMap[cell.category] = {};
    heatmapMap[cell.category][cell.severity] = cell.count;
  }

  const allCategories = Array.from(
    new Set([...CATEGORIES, ...Object.keys(heatmapMap)])
  ).filter((c) => heatmapMap[c]);

  const severities = [0, 1, 2, 3, 4, 5];

  const PRESET_LABELS: { label: string; days: number | null }[] = [
    { label: "All time", days: null },
    { label: "Last 7 days", days: 7 },
    { label: "Last 30 days", days: 30 },
    { label: "Last 90 days", days: 90 },
  ];

  const activePreset =
    !dateFrom && !dateTo
      ? null
      : PRESET_LABELS.find(
          (p) =>
            p.days !== null &&
            dateFrom === offsetDate(-p.days) &&
            dateTo === offsetDate(0)
        )?.days ?? "custom";

  return (
    <div className="flex flex-col gap-8 p-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white">Trends</h1>
          <p className="text-sm text-zinc-400">
            Category × severity heatmap and department breakdown for consultations.
          </p>
        </div>
        <button
          onClick={() => void fetchTrends(selectedDept, dateFrom, dateTo)}
          className="rounded border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800"
        >
          Refresh
        </button>
      </div>

      {/* ── Filters ────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-zinc-800 bg-zinc-900/50 px-5 py-4">
        {/* Department */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Department</label>
          <select
            value={selectedDept}
            onChange={(e) => setSelectedDept(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 focus:outline-none"
          >
            <option value="">All Departments</option>
            {departments.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>

        {/* Period presets */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Period</label>
          <div className="flex gap-1">
            {PRESET_LABELS.map(({ label, days }) => (
              <button
                key={label}
                onClick={() => applyPreset(days)}
                className={`rounded border px-2.5 py-1 text-xs transition ${
                  activePreset === days
                    ? "border-zinc-400 bg-zinc-700 text-white"
                    : "border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Custom date range */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Custom range</label>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
            />
            <span className="text-xs text-zinc-500">–</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
            />
          </div>
        </div>
      </div>

      {loading && <p className="text-sm text-zinc-400">Loading trends…</p>}

      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}

      {!loading && !error && !data?.heatmap.length && (
        <p className="text-sm text-zinc-500">
          No trend data available for the selected filters. Trends appear once
          consultations are submitted.
        </p>
      )}

      {!loading && !!data?.heatmap.length && (
        <>
          {/* Heatmap */}
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              Category × Severity Heatmap
            </h2>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <th className="px-3 py-2 text-left text-xs text-zinc-500">
                      Category (Severity: 0 = Pending/Abstract -&gt; 5 = Critical)
                    </th>
                    {severities.map((s) => (
                      <th
                        key={s}
                        className="px-3 py-2 text-center text-xs text-zinc-400"
                      >
                        {s}
                      </th>
                    ))}
                    <th className="px-3 py-2 text-right text-xs text-zinc-400">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {allCategories.map((cat) => {
                    const rowTotal = severities.reduce(
                      (sum, s) => sum + (heatmapMap[cat]?.[s] ?? 0),
                      0
                    );
                    return (
                      <tr key={cat} className="hover:bg-zinc-800/20">
                        <td className="whitespace-nowrap px-3 py-2 text-zinc-300">
                          {cat}
                        </td>
                        {severities.map((s) => {
                          const count = heatmapMap[cat]?.[s] ?? 0;
                          return (
                            <td key={s} className="px-3 py-2 text-center">
                              {count > 0 ? (
                                <span
                                  className={`inline-block min-w-[2rem] rounded px-1.5 py-0.5 text-xs ${SEVERITY_COLORS[s]}`}
                                >
                                  {count}
                                </span>
                              ) : (
                                <span className="text-zinc-700">—</span>
                              )}
                            </td>
                          );
                        })}
                        <td className="px-3 py-2 text-right text-zinc-300">
                          {rowTotal}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* By Department */}
          {!!data.by_department.length && (
            <section>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                By Department
              </h2>
              <div className="overflow-hidden rounded-lg border border-zinc-800">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-800/60 text-xs uppercase tracking-wider text-zinc-400">
                    <tr>
                      <th className="px-4 py-3 text-left">Department</th>
                      <th className="px-4 py-3 text-right">Consultations</th>
                      <th className="px-4 py-3 text-right">
                        Proposals Submitted
                      </th>
                      <th className="px-4 py-3 text-right">Avg. Severity</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800">
                    {data.by_department.map((d) => (
                      <tr key={d.department} className="hover:bg-zinc-800/30">
                        <td className="px-4 py-3 text-zinc-300">
                          {d.department}
                        </td>
                        <td className="px-4 py-3 text-right text-zinc-300">
                          {d.consultation_count}
                        </td>
                        <td className="px-4 py-3 text-right text-zinc-300">
                          {d.submitted_count}
                        </td>
                        <td className="px-4 py-3 text-right text-zinc-300">
                          {d.avg_severity.toFixed(1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      {/* AI Management Brief */}
      <section className="rounded-lg border border-zinc-800 p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">
              AI Management Brief
            </h2>
            <p className="text-xs text-zinc-500">
              Gemini-generated bullet summary of current consultation trends.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={summaryLang}
              onChange={(e) => setSummaryLang(e.target.value)}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200 focus:outline-none"
            >
              {LANG_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              onClick={() => void generateSummary()}
              disabled={summaryLoading || !data?.heatmap.length}
              className="rounded border border-zinc-600 px-4 py-1.5 text-sm text-zinc-200 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {summaryLoading ? "Generating…" : "Generate Brief"}
            </button>
          </div>
        </div>

        {summaryError && (
          <p className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
            {summaryError}
          </p>
        )}

        {summary && (
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
            {summary}
          </div>
        )}

        {!summary && !summaryError && !summaryLoading && (
          <p className="text-sm text-zinc-600">
            Click &quot;Generate Brief&quot; to produce an AI-written management summary.
          </p>
        )}
      </section>
    </div>
  );
}
