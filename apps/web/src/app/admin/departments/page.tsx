"use client";

import { useCallback, useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface Department {
  id: string;
  name: string;
}

export default function DepartmentsPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  const token = () => localStorage.getItem("admin_token") ?? "";

  const fetchDepartments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/departments`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (!res.ok) {
        setError(`Failed to load departments (${res.status}).`);
        return;
      }
      setDepartments((await res.json()) as Department[]);
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDepartments();
  }, [fetchDepartments]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/admin/departments`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token()}`,
        },
        body: JSON.stringify({ name: newName.trim() }),
      });
      if (!res.ok) {
        const d = (await res.json()) as { detail?: string };
        setError(d.detail ?? "Failed to add department.");
        return;
      }
      setNewName("");
      await fetchDepartments();
    } catch {
      setError("Network error.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 p-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Departments</h1>
        <p className="text-sm text-zinc-400">
          Manage the list of departments shown to employees.
        </p>
      </div>

      {/* Add form */}
      <form
        onSubmit={(e) => void handleAdd(e)}
        className="flex max-w-sm items-center gap-3"
      >
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New department name"
          className="flex-1 rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-500 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={saving || newName.trim().length === 0}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-50"
        >
          {saving ? "Adding…" : "Add"}
        </button>
      </form>

      {error && (
        <p className="max-w-sm rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      {loading && <p className="text-sm text-zinc-400">Loading…</p>}

      {!loading && departments.length === 0 && (
        <p className="text-sm text-zinc-500">No departments registered.</p>
      )}

      {!loading && departments.length > 0 && (
        <div className="max-w-sm overflow-hidden rounded-lg border border-zinc-800">
          <ul className="divide-y divide-zinc-800">
            {departments.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between px-4 py-3 text-sm text-zinc-300"
              >
                {d.name}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
