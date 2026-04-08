"use client";

import { useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface TrendItem {
  category: string | null;
  department: string | null;
  count: number;
  avg_severity: number;
}

export default function TrendsPage() {
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchTrends = async () => {
      setLoading(true);
      setError(null);
      const token = localStorage.getItem("admin_token") ?? "";
      try {
        const res = await fetch(`${API_URL}/admin/trends`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          setError(`Failed to load trends (${res.status}).`);
          return;
        }
        setTrends((await res.json()) as TrendItem[]);
      } catch {
        setError("Network error.");
      } finally {
        setLoading(false);
      }
    };
    void fetchTrends();
  }, []);

  return (
    <div className="flex flex-col gap-6 p-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Trends</h1>
        <p className="text-sm text-zinc-400">
          Aggregated view of issues by category and department.
        </p>
      </div>

      {loading && <p className="text-sm text-zinc-400">Loading trends…</p>}

      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}

      {!loading && !error && trends.length === 0 && (
        <p className="text-sm text-zinc-500">
          No trend data available yet. Trends appear once consultations are
          submitted.
        </p>
      )}

      {!loading && trends.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-800/60 text-xs uppercase tracking-wider text-zinc-400">
              <tr>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-left">Department</th>
                <th className="px-4 py-3 text-right">Count</th>
                <th className="px-4 py-3 text-right">Avg. Severity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {trends.map((t, i) => (
                <tr key={i} className="hover:bg-zinc-800/30">
                  <td className="px-4 py-3 text-zinc-300">
                    {t.category ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-zinc-300">
                    {t.department ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-right text-zinc-300">
                    {t.count}
                  </td>
                  <td className="px-4 py-3 text-right text-zinc-300">
                    {t.avg_severity.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
