"use client";

import { useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type AdminStatus = "New" | "Under Review" | "Resolved" | "Rejected";

interface Proposal {
  id: string;
  department: string | null;
  category: string | null;
  severity: number;
  summary: string | null;
  user_name: string | null;
  user_email: string | null;
  admin_status: AdminStatus;
  is_submitted: boolean;
  created_at: string;
}

const STATUS_COLORS: Record<AdminStatus, string> = {
  New: "bg-blue-500/20 text-blue-300",
  "Under Review": "bg-yellow-500/20 text-yellow-300",
  Resolved: "bg-green-500/20 text-green-300",
  Rejected: "bg-red-500/20 text-red-300",
};

function severityBadge(n: number) {
  if (n >= 4) return "bg-red-500/20 text-red-300";
  if (n >= 2) return "bg-yellow-500/20 text-yellow-300";
  return "bg-zinc-700 text-zinc-300";
}

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProposals = async () => {
    setLoading(true);
    setError(null);
    const token = localStorage.getItem("admin_token") ?? "";
    try {
      const res = await fetch(`${API_URL}/admin/proposals`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        setError(`Failed to load proposals (${res.status}).`);
        return;
      }
      const data = (await res.json()) as Proposal[];
      setProposals(data);
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchProposals();
  }, []);

  return (
    <div className="flex flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Proposals</h1>
          <p className="text-sm text-zinc-400">
            Submitted improvement proposals from employees.
          </p>
        </div>
        <button
          onClick={() => void fetchProposals()}
          className="rounded border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800"
        >
          Refresh
        </button>
      </div>

      {loading && (
        <p className="text-sm text-zinc-400">Loading proposals…</p>
      )}

      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}

      {!loading && !error && proposals.length === 0 && (
        <p className="text-sm text-zinc-500">No submitted proposals yet.</p>
      )}

      {!loading && proposals.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-800/60 text-xs uppercase tracking-wider text-zinc-400">
              <tr>
                <th className="px-4 py-3 text-left">Department</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-left">Severity</th>
                <th className="px-4 py-3 text-left">Summary</th>
                <th className="px-4 py-3 text-left">Submitted by</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {proposals.map((p) => (
                <tr key={p.id} className="hover:bg-zinc-800/30">
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
                  <td className="max-w-xs px-4 py-3 text-zinc-300">
                    <span className="line-clamp-2">
                      {p.summary ?? "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-zinc-300">
                    {p.user_name
                      ? `${p.user_name}${p.user_email ? ` <${p.user_email}>` : ""}`
                      : "Anonymous"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[p.admin_status] ?? "bg-zinc-700 text-zinc-300"}`}
                    >
                      {p.admin_status}
                    </span>
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
    </div>
  );
}
