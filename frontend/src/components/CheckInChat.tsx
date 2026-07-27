"use client";

/**
 * CheckInChat — Step 2 of the check-in flow.
 * Conversational AI interface for contextual symptom capture.
 * Adaptive tone: brief / gentle / engaged based on patient messages.
 */

import { useEffect, useRef, useState } from "react";
import { useCheckInStore } from "@/store/checkInStore";
import { checkInApi } from "@/lib/api";
import type { ConfirmationSummary } from "@/store/checkInStore";

interface Props {
  onConfirmationReady: (summary: ConfirmationSummary) => void;
}

export function CheckInChat({ onConfirmationReady }: Props) {
  const {
    sessionId,
    messages,
    isLoading,
    addMessage,
    setLoading,
    setConfirmationSummary,
    setError,
  } = useCheckInStore();

  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || !sessionId || isLoading) return;

    setInput("");
    addMessage({ role: "user", content: text });
    setLoading(true);

    try {
      const res = await checkInApi.message(sessionId, text);
      addMessage({ role: "assistant", content: res.ai_message });

      if (res.status === "awaiting_confirmation" && res.confirmation_summary) {
        setConfirmationSummary(res.confirmation_summary);
        onConfirmationReady(res.confirmation_summary);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      setError(msg);
      addMessage({ role: "assistant", content: "I had a moment — could you try again?" });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Chat messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pb-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-brand-600 text-white rounded-br-sm"
                  : "bg-white text-slate-700 border border-slate-200 rounded-bl-sm"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3">
              <span className="flex gap-1">
                <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" />
              </span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2 pt-2 border-t border-slate-200">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type how you're feeling today…"
          rows={2}
          disabled={isLoading}
          className="flex-1 resize-none rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-60"
        />
        <button
          onClick={() => void sendMessage()}
          disabled={isLoading || !input.trim()}
          className="self-end bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white rounded-xl px-4 py-3 text-sm font-semibold transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  );
}
