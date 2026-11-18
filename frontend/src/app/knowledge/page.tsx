"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { BookOpen, Search, Plus, Sparkles, CheckCircle2, AlertCircle } from "lucide-react";

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);

  const fetchDocs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest("/knowledge/documents");
      setDocuments(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load Knowledge Base documents.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      const res = await apiRequest(`/knowledge/search?q=${encodeURIComponent(searchQuery)}&top_k=4`);
      setSearchResults(res);
    } catch (err) {
      console.error(err);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Approved Knowledge Base & RAG Index</h1>
        <p className="text-sm text-slate-500">Verified IT SOPs, troubleshooting procedures, and embeddings for AI retrieval</p>
      </div>

      {/* RAG Search Playground */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
        <form onSubmit={handleSearch} className="flex gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
            <input
              type="text"
              placeholder="Test RAG retrieval (e.g. 'Wi-Fi 169.254 DHCP failure', 'print spooler stopped')..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>
          <button
            type="submit"
            disabled={searching}
            className="px-4 py-2 bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold rounded-lg shadow-sm transition flex items-center space-x-1.5"
          >
            <Sparkles className="w-4 h-4" />
            <span>Search RAG</span>
          </button>
        </form>

        {searchResults && (
          <div className="pt-2 space-y-3">
            <div className="text-xs font-bold text-slate-700 uppercase">
              RAG Similarity Ranked Results ({searchResults.length})
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {searchResults.map((r, i) => (
                <div key={i} className="p-3.5 rounded-lg border border-sky-100 bg-sky-50/50 space-y-1.5 text-xs">
                  <div className="flex items-center justify-between font-bold text-sky-900">
                    <span>{r.doc_id}: {r.title}</span>
                    <span className="font-mono text-[11px] bg-white px-2 py-0.5 rounded border border-sky-200">
                      Score: {r.similarity_score}
                    </span>
                  </div>
                  <p className="text-slate-600 line-clamp-3 whitespace-pre-wrap">{r.chunk_text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Document Catalog */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-4 border-b border-slate-100 font-bold text-sm text-slate-800">
          Standard Operating Procedures ({documents.length})
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-slate-400">Loading documents...</div>
        ) : error ? (
          <div className="p-8 text-center space-y-2">
            <AlertCircle className="w-6 h-6 text-rose-500 mx-auto" />
            <div className="text-xs text-rose-600">{error}</div>
            <button
              onClick={fetchDocs}
              className="px-3.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold"
            >
              Retry
            </button>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {documents.map((doc) => (
              <div key={doc.id} className="p-4 sm:p-5 flex flex-col sm:flex-row justify-between items-start gap-4">
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-xs font-bold text-sky-700">{doc.doc_id}</span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                      v{doc.version}
                    </span>
                    <span className="text-[10px] font-semibold text-slate-400">&bull; {doc.category}</span>
                  </div>
                  <h3 className="text-sm font-bold text-slate-900">{doc.title}</h3>
                  <div className="text-xs text-slate-500">
                    Type: <span className="font-medium text-slate-700">{doc.source_type}</span> &bull; Indexed Chunks: <span className="font-medium text-slate-700">{doc.chunk_count}</span>
                  </div>
                </div>

                <div className="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-100 flex items-center space-x-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Approved SOP</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
