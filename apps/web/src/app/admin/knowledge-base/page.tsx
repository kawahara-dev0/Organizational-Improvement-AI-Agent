"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface Chunk {
  id: string;
  source_file: string;
  category: string | null;
  chunk_index: number;
  content: string;
}

export default function KnowledgeBasePage() {
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const token = () => localStorage.getItem("admin_token") ?? "";

  const fetchChunks = useCallback(async (source?: string) => {
    setLoading(true);
    setError(null);
    try {
      const params = source ? `?source_file=${encodeURIComponent(source)}` : "";
      const res = await fetch(`${API_URL}/knowledge/chunks${params}`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (!res.ok) {
        setError(`Failed to load chunks (${res.status}).`);
        return;
      }
      setChunks((await res.json()) as Chunk[]);
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchChunks();
  }, [fetchChunks]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadMsg(null);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API_URL}/knowledge/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token()}` },
        body: form,
      });
      if (!res.ok) {
        const d = (await res.json()) as { detail?: string };
        setError(d.detail ?? "Upload failed.");
        return;
      }
      const d = (await res.json()) as { chunks_upserted?: number };
      setUploadMsg(
        `Upload complete — ${d.chunks_upserted ?? "?"} chunks upserted.`,
      );
      if (fileRef.current) fileRef.current.value = "";
      await fetchChunks();
    } catch {
      setError("Network error.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 p-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Knowledge Base</h1>
        <p className="text-sm text-zinc-400">
          Upload documents to populate the RAG knowledge base.
        </p>
      </div>

      {/* Upload form */}
      <form
        onSubmit={(e) => void handleUpload(e)}
        className="flex max-w-lg items-center gap-3"
      >
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.xlsx"
          className="flex-1 rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-300 file:mr-3 file:rounded file:border-0 file:bg-zinc-700 file:px-2 file:py-1 file:text-xs file:text-zinc-300"
        />
        <button
          type="submit"
          disabled={uploading}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </form>

      {uploadMsg && (
        <p className="max-w-lg rounded border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
          {uploadMsg}
        </p>
      )}
      {error && (
        <p className="max-w-lg rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      {/* Filter */}
      <div className="flex max-w-sm items-center gap-3">
        <input
          type="text"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          placeholder="Filter by source file…"
          className="flex-1 rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-500 outline-none focus:border-blue-500"
        />
        <button
          onClick={() => void fetchChunks(sourceFilter || undefined)}
          className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-300 transition hover:bg-zinc-800"
        >
          Filter
        </button>
      </div>

      {loading && <p className="text-sm text-zinc-400">Loading chunks…</p>}

      {!loading && chunks.length === 0 && (
        <p className="text-sm text-zinc-500">No documents in knowledge base.</p>
      )}

      {!loading && chunks.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-800/60 text-xs uppercase tracking-wider text-zinc-400">
              <tr>
                <th className="px-4 py-3 text-left">Source file</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-left">#</th>
                <th className="px-4 py-3 text-left">Content preview</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {chunks.map((c) => (
                <tr key={c.id} className="hover:bg-zinc-800/30">
                  <td className="max-w-[12rem] truncate px-4 py-3 text-zinc-300">
                    {c.source_file}
                  </td>
                  <td className="px-4 py-3 text-zinc-400">
                    {c.category ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-zinc-400">{c.chunk_index}</td>
                  <td className="max-w-md px-4 py-3 text-zinc-400">
                    <span className="line-clamp-1">{c.content}</span>
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
