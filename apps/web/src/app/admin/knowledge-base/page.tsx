"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Version {
  id: string;
  version_no: number;
  source_file: string;
  is_active: boolean;
  chunk_count: number;
  created_at: string;
}

interface Chunk {
  id: string;
  chunk_index: number | null;
  content: string;
  page_number: string | null;
}

interface Document {
  id: string;
  title: string;
  category: string;
  version_id: string | null;
  version_no: number | null;
  source_file: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  // detail view
  versions?: Version[];
  chunks?: Chunk[];
}

function token() {
  return localStorage.getItem("admin_token") ?? "";
}

// ── Sub-component: Document row ───────────────────────────────────────────────

function DocumentRow({
  doc,
  onRefresh,
}: {
  doc: Document;
  onRefresh: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<Document | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // edit meta
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(doc.title);
  const [editCategory, setEditCategory] = useState(doc.category);
  const [metaSaving, setMetaSaving] = useState(false);

  // new version upload
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const newVersionRef = useRef<HTMLInputElement>(null);
  const [newVersionFileName, setNewVersionFileName] = useState("");

  // delete
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [rowError, setRowError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    setDetailLoading(true);
    try {
      const res = await fetch(`${API_URL}/knowledge/documents/${doc.id}`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (res.ok) setDetail((await res.json()) as Document);
    } finally {
      setDetailLoading(false);
    }
  }, [doc.id]);

  const toggleExpand = () => {
    if (!expanded && !detail) void loadDetail();
    setExpanded((v) => !v);
  };

  const openNewVersionPanel = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!expanded) setExpanded(true);
    if (!detail) void loadDetail();
  };

  const saveMeta = async () => {
    if (!editTitle.trim()) return;
    setMetaSaving(true);
    setRowError(null);
    try {
      const res = await fetch(`${API_URL}/knowledge/documents/${doc.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token()}`,
        },
        body: JSON.stringify({
          title: editTitle.trim(),
          category: editCategory.trim(),
        }),
      });
      if (!res.ok) {
        const d = (await res.json()) as { detail?: string };
        setRowError(d.detail ?? "Failed to save.");
        return;
      }
      setEditing(false);
      onRefresh();
    } catch {
      setRowError("Network error.");
    } finally {
      setMetaSaving(false);
    }
  };

  const uploadVersion = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = newVersionRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadMsg(null);
    setRowError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(
        `${API_URL}/knowledge/documents/${doc.id}/upload`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token()}` },
          body: form,
        },
      );
      if (!res.ok) {
        const d = (await res.json()) as { detail?: string };
        setRowError(d.detail ?? "Upload failed.");
        return;
      }
      const d = (await res.json()) as { version_no: number; chunks_created: number };
      setUploadMsg(
        `v${d.version_no} uploaded — ${d.chunks_created} chunks.`,
      );
      if (newVersionRef.current) newVersionRef.current.value = "";
      await loadDetail();
      onRefresh();
    } catch {
      setRowError("Network error.");
    } finally {
      setUploading(false);
    }
  };

  const deleteDocument = async () => {
    setRowError(null);
    try {
      const res = await fetch(`${API_URL}/knowledge/documents/${doc.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (!res.ok && res.status !== 204) {
        const d = (await res.json()) as { detail?: string };
        setRowError(d.detail ?? "Delete failed.");
        return;
      }
      onRefresh();
    } catch {
      setRowError("Network error.");
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800">
      {/* ── Header row ── */}
      <div className="flex items-center gap-3 bg-zinc-800/50 px-4 py-3">
        <button
          onClick={toggleExpand}
          className="flex flex-1 items-start gap-2 text-left"
        >
          <span
            className={`mt-0.5 shrink-0 text-xs text-zinc-400 transition-transform ${expanded ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          <div className="min-w-0">
            {editing ? (
              <div
                className="flex flex-wrap items-center gap-2"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-sm text-white outline-none focus:border-blue-500"
                  autoFocus
                />
                <input
                  type="text"
                  value={editCategory}
                  onChange={(e) => setEditCategory(e.target.value)}
                  placeholder="Category"
                  className="w-32 rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-xs text-zinc-300 outline-none focus:border-blue-500"
                />
                <button
                  onClick={() => void saveMeta()}
                  disabled={metaSaving || editTitle.trim().length === 0}
                  className="rounded bg-blue-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                >
                  {metaSaving ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={() => setEditing(false)}
                  className="rounded border border-zinc-600 px-2 py-0.5 text-xs text-zinc-400 hover:bg-zinc-700"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-white">{doc.title}</span>
                {doc.category && (
                  <span className="rounded bg-zinc-700 px-2 py-0.5 text-xs text-zinc-300">
                    {doc.category}
                  </span>
                )}
                <span className="text-xs text-zinc-500">
                  v{doc.version_no ?? "—"} · {doc.chunk_count ?? 0} chunks ·{" "}
                  {doc.source_file ?? "—"}
                </span>
              </div>
            )}
          </div>
        </button>

        {/* Actions */}
        {!editing && !confirmDelete && (
          <div className="flex shrink-0 gap-2">
            <button
              onClick={openNewVersionPanel}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-700 hover:text-white"
            >
              New Version
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setEditing(true);
                setExpanded(true);
                if (!detail) void loadDetail();
              }}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-700 hover:text-white"
            >
              Edit
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setConfirmDelete(true);
              }}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:border-red-500/50 hover:bg-red-500/10 hover:text-red-400"
            >
              Delete
            </button>
          </div>
        )}
        {confirmDelete && (
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-xs text-zinc-300">Delete this document?</span>
            <button
              onClick={() => void deleteDocument()}
              className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-500"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="rounded border border-zinc-600 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-700"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {rowError && (
        <p className="bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {rowError}
        </p>
      )}

      {/* ── Expanded detail ── */}
      {expanded && (
        <div className="divide-y divide-zinc-800/60 bg-zinc-950">
          {detailLoading && (
            <p className="px-6 py-3 text-xs text-zinc-400">Loading…</p>
          )}

          {detail && (
            <>
              {/* Version history */}
              <div className="px-6 py-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  Version History
                </p>
                <ul className="space-y-1">
                  {detail.versions?.map((v) => (
                    <li
                      key={v.id}
                      className="flex items-center gap-3 text-xs text-zinc-400"
                    >
                      <span
                        className={`rounded px-1.5 py-0.5 font-medium ${v.is_active ? "bg-green-500/20 text-green-300" : "bg-zinc-800 text-zinc-500"}`}
                      >
                        v{v.version_no}
                      </span>
                      <span>{v.source_file}</span>
                      <span>{v.chunk_count} chunks</span>
                      <span className="text-zinc-600">
                        {new Date(v.created_at).toLocaleDateString()}
                      </span>
                      {v.is_active && (
                        <span className="rounded bg-green-500/20 px-1.5 py-0.5 text-xs text-green-300">
                          Active
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Upload new version */}
              <div className="px-6 py-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  Upload New Version
                </p>
                <form
                  onSubmit={(e) => void uploadVersion(e)}
                  className="flex items-center gap-3"
                >
                  <input
                    ref={newVersionRef}
                    type="file"
                    accept=".pdf,.docx,.xlsx"
                    className="hidden"
                    onChange={(e) =>
                      setNewVersionFileName(e.target.files?.[0]?.name ?? "")
                    }
                  />
                  <button
                    type="button"
                    onClick={() => newVersionRef.current?.click()}
                    className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
                  >
                    Choose File
                  </button>
                  <span className="max-w-48 truncate text-xs text-zinc-500">
                    {newVersionFileName || "No file selected"}
                  </span>
                  <button
                    type="submit"
                    disabled={uploading}
                    className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {uploading ? "Uploading…" : "Upload"}
                  </button>
                </form>
                {uploadMsg && (
                  <p className="mt-1 text-xs text-green-300">{uploadMsg}</p>
                )}
              </div>

              {/* Chunks (view only) */}
              {detail.chunks && detail.chunks.length > 0 && (
                <div className="px-6 py-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    Chunks — Active Version ({detail.chunks.length})
                  </p>
                  <ul className="max-h-80 space-y-2 overflow-y-auto pr-1">
                    {detail.chunks.map((c) => (
                      <li
                        key={c.id}
                        className="flex gap-3 rounded bg-zinc-800/40 px-3 py-2 text-xs"
                      >
                        <span className="shrink-0 text-zinc-500">
                          #{c.chunk_index ?? "?"}
                        </span>
                        <span className="text-zinc-300 leading-relaxed">
                          {c.content}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // orphan chunks
  const [orphanCount, setOrphanCount] = useState<number | null>(null);
  const [cleaningOrphans, setCleaningOrphans] = useState(false);
  const [orphanMsg, setOrphanMsg] = useState<string | null>(null);

  // create document form
  const [showCreate, setShowCreate] = useState(false);
  const [createTitle, setCreateTitle] = useState("");
  const [createCategory, setCreateCategory] = useState("");
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState<string | null>(null);
  const createFileRef = useRef<HTMLInputElement>(null);
  const [createFileName, setCreateFileName] = useState("");

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docsRes, orphanRes] = await Promise.all([
        fetch(`${API_URL}/knowledge/documents`, {
          headers: { Authorization: `Bearer ${token()}` },
        }),
        fetch(`${API_URL}/knowledge/orphan-chunks`, {
          headers: { Authorization: `Bearer ${token()}` },
        }),
      ]);
      if (!docsRes.ok) {
        setError(`Failed to load documents (${docsRes.status}).`);
        return;
      }
      setDocuments((await docsRes.json()) as Document[]);
      if (orphanRes.ok) {
        const od = (await orphanRes.json()) as { count: number };
        setOrphanCount(od.count);
      }
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleCleanOrphans = async () => {
    if (!confirm(`Delete ${String(orphanCount)} legacy chunks? This cannot be undone.`)) return;
    setCleaningOrphans(true);
    setOrphanMsg(null);
    try {
      const res = await fetch(`${API_URL}/knowledge/orphan-chunks`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (!res.ok) {
        setOrphanMsg("Failed to delete legacy chunks.");
        return;
      }
      const d = (await res.json()) as { deleted: number };
      setOrphanCount(0);
      setOrphanMsg(`Deleted ${String(d.deleted)} legacy chunks.`);
    } catch {
      setOrphanMsg("Network error.");
    } finally {
      setCleaningOrphans(false);
    }
  };

  useEffect(() => {
    void fetchDocuments();
  }, [fetchDocuments]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = createFileRef.current?.files?.[0];
    if (!createTitle.trim() || !file) return;
    setCreating(true);
    setCreateMsg(null);
    setError(null);
    const form = new FormData();
    form.append("title", createTitle.trim());
    form.append("category", createCategory.trim());
    form.append("file", file);
    try {
      const res = await fetch(`${API_URL}/knowledge/documents`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: form,
      });
      if (!res.ok) {
        let detail = "Failed to create document.";
        try {
          const d = (await res.json()) as { detail?: string };
          detail = d.detail ?? detail;
        } catch {
          // keep fallback detail
        }
        setError(detail);
        return;
      }
      const d = (await res.json()) as { chunks_created: number };
      setCreateMsg(`Document created — ${d.chunks_created} chunks embedded.`);
      setCreateTitle("");
      setCreateCategory("");
      if (createFileRef.current) createFileRef.current.value = "";
      setCreateFileName("");
      setShowCreate(false);
      await fetchDocuments();
    } catch {
      setError("Network error.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 p-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Knowledge Base</h1>
        <p className="text-sm text-zinc-400">
          Manage documents for RAG retrieval. To update content, upload a new
          version of the source file.
        </p>
        {!showCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="mt-3 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500"
          >
            + New Document
          </button>
        )}
      </div>

      {/* Create form */}
      {showCreate && (
        <form
          onSubmit={(e) => void handleCreate(e)}
          className="flex max-w-xl flex-col gap-3 rounded-lg border border-zinc-700 bg-zinc-900 p-4"
        >
          <p className="text-sm font-medium text-white">New Document</p>
          <input
            type="text"
            value={createTitle}
            onChange={(e) => setCreateTitle(e.target.value)}
            placeholder="Document title (e.g. Work Rules)"
            required
            className="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-500 outline-none focus:border-blue-500"
          />
          <input
            type="text"
            value={createCategory}
            onChange={(e) => setCreateCategory(e.target.value)}
            placeholder="Category (optional, e.g. policy)"
            className="rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-500 outline-none focus:border-blue-500"
          />
          <div className="flex items-center gap-3">
            <input
              ref={createFileRef}
              type="file"
              accept=".pdf,.docx,.xlsx"
              required
              className="hidden"
              onChange={(e) => setCreateFileName(e.target.files?.[0]?.name ?? "")}
            />
            <button
              type="button"
              onClick={() => createFileRef.current?.click()}
              className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              Choose File
            </button>
            <span className="max-w-64 truncate text-sm text-zinc-500">
              {createFileName || "No file selected"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={
                creating || createTitle.trim().length === 0 || createFileName.length === 0
              }
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {creating ? "Uploading…" : "Create & Upload"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowCreate(false);
                setCreateTitle("");
                setCreateCategory("");
                setCreateFileName("");
                if (createFileRef.current) createFileRef.current.value = "";
              }}
              disabled={creating}
              className="rounded border border-zinc-700 px-4 py-2 text-sm text-zinc-400 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Orphan / legacy chunk warning */}
      {orphanCount !== null && orphanCount > 0 && (
        <div className="flex max-w-xl flex-col gap-2 rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-4">
          <p className="text-sm font-medium text-yellow-300">
            ⚠ {orphanCount} legacy chunk{orphanCount !== 1 ? "s" : ""} detected
          </p>
          <p className="text-xs text-yellow-200/70">
            These chunks were uploaded before the document management system was
            introduced. They are{" "}
            <strong>no longer used for RAG retrieval</strong> and can be safely
            removed. Re-upload the source files through{" "}
            <em>+ New Document</em> if needed.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => void handleCleanOrphans()}
              disabled={cleaningOrphans}
              className="rounded bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-500 disabled:opacity-50"
            >
              {cleaningOrphans ? "Deleting…" : "Delete Legacy Chunks"}
            </button>
            {orphanMsg && (
              <span className="text-xs text-yellow-300">{orphanMsg}</span>
            )}
          </div>
        </div>
      )}
      {orphanCount === 0 && orphanMsg && (
        <p className="max-w-xl rounded border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
          {orphanMsg}
        </p>
      )}

      {createMsg && (
        <p className="max-w-xl rounded border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
          {createMsg}
        </p>
      )}
      {error && (
        <p className="max-w-xl rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      {loading && <p className="text-sm text-zinc-400">Loading…</p>}

      {!loading && documents.length === 0 && (
        <p className="text-sm text-zinc-500">
          No documents in knowledge base. Use &quot;+ New Document&quot; to add one.
        </p>
      )}

      {/* Document list */}
      <div className="flex flex-col gap-3">
        {documents.map((doc) => (
          <DocumentRow key={doc.id} doc={doc} onRefresh={() => void fetchDocuments()} />
        ))}
      </div>
    </div>
  );
}
