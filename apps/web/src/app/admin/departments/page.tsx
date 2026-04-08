"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface Department {
  id: string;
  name: string;
}

function token() {
  return localStorage.getItem("admin_token") ?? "";
}

export default function DepartmentsPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // add form
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  // inline edit
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);

  // delete confirmation
  const [deletingId, setDeletingId] = useState<string | null>(null);

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

  // focus edit input when entering edit mode
  useEffect(() => {
    if (editingId) editInputRef.current?.focus();
  }, [editingId]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setSaving(true);
    setError(null);
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

  const startEdit = (dept: Department) => {
    setEditingId(dept.id);
    setEditName(dept.name);
    setDeletingId(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditName("");
  };

  const submitEdit = async (id: string) => {
    const name = editName.trim();
    if (!name) return;
    setError(null);
    try {
      const res = await fetch(`${API_URL}/admin/departments/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token()}`,
        },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const d = (await res.json()) as { detail?: string };
        setError(d.detail ?? "Failed to rename department.");
        return;
      }
      setEditingId(null);
      await fetchDepartments();
    } catch {
      setError("Network error.");
    }
  };

  const confirmDelete = async (id: string) => {
    setError(null);
    try {
      const res = await fetch(`${API_URL}/admin/departments/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (!res.ok && res.status !== 204) {
        const d = (await res.json()) as { detail?: string };
        setError(d.detail ?? "Failed to delete department.");
        return;
      }
      setDeletingId(null);
      await fetchDepartments();
    } catch {
      setError("Network error.");
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
        <div className="max-w-lg overflow-hidden rounded-lg border border-zinc-800">
          <ul className="divide-y divide-zinc-800">
            {departments.map((dept) => (
              <li key={dept.id} className="px-4 py-3">
                {editingId === dept.id ? (
                  /* ── Inline edit row ── */
                  <div className="flex items-center gap-2">
                    <input
                      ref={editInputRef}
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void submitEdit(dept.id);
                        if (e.key === "Escape") cancelEdit();
                      }}
                      className="flex-1 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm text-white outline-none focus:border-blue-500"
                    />
                    <button
                      onClick={() => void submitEdit(dept.id)}
                      disabled={editName.trim().length === 0}
                      className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="rounded border border-zinc-600 px-3 py-1 text-xs text-zinc-400 hover:bg-zinc-700"
                    >
                      Cancel
                    </button>
                  </div>
                ) : deletingId === dept.id ? (
                  /* ── Delete confirmation row ── */
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-zinc-300">
                      Delete &quot;{dept.name}&quot;? This cannot be undone.
                    </span>
                    <div className="flex shrink-0 gap-2">
                      <button
                        onClick={() => void confirmDelete(dept.id)}
                        className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500"
                      >
                        Delete
                      </button>
                      <button
                        onClick={() => setDeletingId(null)}
                        className="rounded border border-zinc-600 px-3 py-1 text-xs text-zinc-400 hover:bg-zinc-700"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  /* ── Normal row ── */
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-zinc-300">{dept.name}</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => startEdit(dept)}
                        className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-400 transition hover:bg-zinc-700 hover:text-white"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => {
                          setDeletingId(dept.id);
                          setEditingId(null);
                        }}
                        className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-400 transition hover:border-red-500/50 hover:bg-red-500/10 hover:text-red-400"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
