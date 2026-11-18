"use client";

import { useState, useEffect, useRef } from "react";
import Navbar from "@/components/Navbar";
import { MessageSquare, Send, Bot, User, Sparkles, RefreshCw, Cpu, Server, ShieldCheck } from "lucide-react";

interface ChatMessage {
  id: string;
  sender: "user" | "bot";
  text: string;
  sources?: Array<{ doc_id: string; title: string; category?: string }>;
  tools?: string[];
  provider?: string;
  timestamp: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      sender: "bot",
      text: "Hello! I am the AISD AI IT Assistant. I can help diagnose network, printing, and OS issues across Windows and Linux workstations. How can I assist you today?",
      sources: [],
      tools: [],
      provider: "central_rag_ai",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lbStatus, setLbStatus] = useState<any>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchLbStatus = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/chat/loadbalancer/status");
      if (res.ok) {
        const data = await res.json();
        setLbStatus(data);
      }
    } catch {
      // Backend may be on another host/port
    }
  };

  useEffect(() => {
    fetchLbStatus();
    const timer = setInterval(fetchLbStatus, 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async (textToSend?: string) => {
    const text = (textToSend || input).trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      sender: "user",
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (!textToSend) setInput("");
    setLoading(true);

    try {
      const apiHost = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1";
      const res = await fetch(`http://${apiHost}:8000/api/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: messages.slice(-4).map((m) => ({
            role: m.sender === "user" ? "user" : "assistant",
            content: m.text,
          })),
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const botMsg: ChatMessage = {
          id: `b-${Date.now()}`,
          sender: "bot",
          text: data.reply,
          sources: data.sources || [],
          tools: data.recommended_tools || [],
          provider: data.provider || "ollama",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        setMessages((prev) => [...prev, botMsg]);
      } else {
        throw new Error("Chat service returned error");
      }
    } catch {
      // Fallback
      setMessages((prev) => [
        ...prev,
        {
          id: `b-${Date.now()}`,
          sender: "bot",
          text: "I was unable to contact the central Ollama server directly. If you are experiencing a 169.254 APIPA IP or DNS resolution failure, please run tool `renew_dhcp` or `flush_dns_cache` via the endpoint agent.",
          sources: [{ doc_id: "KB-NET-001", title: "DHCP Lease Failure SOP" }],
          tools: ["renew_dhcp"],
          provider: "offline_fallback",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const sampleQueries = [
    "Wi-Fi connected but No Internet and IP starts with 169.254",
    "Ping to 8.8.8.8 works but campus websites fail to resolve",
    "Linux lab workstation cannot print, CUPS daemon stopped",
    "Default gateway is unreachable on subnet",
  ];

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 flex flex-col">
        {/* Header Bar */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 mb-4 shadow-sm flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-sky-600 flex items-center justify-center text-white shadow-sm">
              <Bot className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                AISD AI IT Incident Assistant
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-sky-100 text-sky-800">
                  <Sparkles className="w-3 h-3 mr-1" />
                  RAG Hybrid
                </span>
              </h1>
              <p className="text-xs text-slate-500">
                Grounding answers in college SOPs with dynamic load balancing across Ollama nodes
              </p>
            </div>
          </div>

          {/* Load Balancer Pill */}
          <div className="flex items-center gap-2 text-xs font-medium bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-lg text-slate-700">
            <Server className="w-4 h-4 text-emerald-600" />
            <span>
              Ollama Load Balancer:{" "}
              <strong className="text-emerald-700">
                {lbStatus ? `${lbStatus.healthy_nodes}/${lbStatus.total_nodes} Healthy` : "Active"}
              </strong>
            </span>
          </div>
        </div>

        {/* Chat Window */}
        <div className="flex-1 bg-white border border-slate-200 rounded-xl p-4 sm:p-6 shadow-sm overflow-y-auto flex flex-col space-y-4 max-h-[60vh]">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex gap-3 max-w-3xl ${m.sender === "user" ? "ml-auto flex-row-reverse" : "mr-auto"}`}
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-white ${
                  m.sender === "user" ? "bg-slate-700" : "bg-sky-600"
                }`}
              >
                {m.sender === "user" ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>

              <div
                className={`rounded-2xl px-4 py-3 text-sm shadow-sm ${
                  m.sender === "user"
                    ? "bg-sky-600 text-white rounded-tr-none"
                    : "bg-slate-50 text-slate-900 border border-slate-200 rounded-tl-none"
                }`}
              >
                <p className="whitespace-pre-wrap leading-relaxed">{m.text}</p>

                {/* Sources & Citations */}
                {m.sources && m.sources.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-slate-200/60">
                    <p className="text-xs font-semibold text-slate-500 mb-1 flex items-center gap-1">
                      <ShieldCheck className="w-3.5 h-3.5 text-sky-600" />
                      Standard Operating Procedures Grounded:
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {m.sources.map((s, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800"
                        >
                          [{s.doc_id}] {s.title}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recommended Tools */}
                {m.tools && m.tools.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-slate-500 font-medium">Recommended Tool:</span>
                    {m.tools.map((t) => (
                      <span
                        key={t}
                        className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-semibold bg-emerald-100 text-emerald-800"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}

                <div className="mt-1 text-[10px] text-slate-400 text-right">{m.timestamp}</div>
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-3 max-w-xl mr-auto items-center text-slate-500 text-sm italic">
              <div className="w-8 h-8 rounded-full bg-sky-100 flex items-center justify-center text-sky-600">
                <RefreshCw className="w-4 h-4 animate-spin" />
              </div>
              Retrieving SOP knowledge & evaluating inference...
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Sample Prompts */}
        <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
          <span className="text-xs font-semibold text-slate-500 shrink-0">Try asking:</span>
          {sampleQueries.map((q, idx) => (
            <button
              key={idx}
              onClick={() => handleSend(q)}
              className="text-xs bg-white border border-slate-200 hover:border-sky-300 hover:bg-sky-50 text-slate-700 px-3 py-1.5 rounded-full whitespace-nowrap transition-colors shadow-2xs"
            >
              {q}
            </button>
          ))}
        </div>

        {/* Input Bar */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="mt-3 flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe your IT issue (e.g. Wi-Fi has 169.254 APIPA IP, or Linux printing error)..."
            disabled={loading}
            className="flex-1 bg-white border border-slate-300 focus:border-sky-500 focus:ring-2 focus:ring-sky-200 rounded-xl px-4 py-3 text-sm text-slate-900 outline-none transition shadow-xs"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white px-5 py-3 rounded-xl font-medium text-sm flex items-center gap-2 shadow-sm transition-colors"
          >
            <Send className="w-4 h-4" />
            <span>Send</span>
          </button>
        </form>
      </main>
    </div>
  );
}
