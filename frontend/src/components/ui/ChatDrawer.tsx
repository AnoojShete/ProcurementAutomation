import { useState, useRef, useEffect } from "react";
import { Drawer } from "./Drawer";
import { sendMessage, sendMessageStream, type ChatMessage } from "@/api/chat";
import { ArrowUp, Sparkles, MessageSquarePlus, Copy, Check, RotateCcw, FileText, Inbox, KeyRound, ShieldCheck } from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const QUICK_PROMPTS = [
  { icon: FileText, text: "What is our procurement summary?" },
  { icon: Inbox, text: "Show my pending purchase requests" },
  { icon: KeyRound, text: "Are there any SaaS license anomalies?" },
  { icon: ShieldCheck, text: "Check risk score for Acme Corp" },
];

const ERROR_REPLY = "Sorry, I encountered an error connecting to the AI.";

// Markdown inside an assistant reply, styled with the Ledger tokens.
const MARKDOWN =
  "[&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:ml-5 [&_ul]:mb-2 [&_ol]:list-decimal [&_ol]:ml-5 [&_ol]:mb-2 [&_li]:my-0.5 " +
  "[&_strong]:font-semibold [&_strong]:text-ink [&_a]:text-accent [&_a]:underline " +
  "[&_code]:font-mono [&_code]:text-caption [&_code]:bg-sheet-sunk [&_code]:rounded [&_code]:px-1 " +
  "[&_pre]:bg-sheet-sunk [&_pre]:border [&_pre]:border-rule [&_pre]:rounded-md [&_pre]:p-3 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre_code]:p-0 [&_pre_code]:bg-transparent " +
  "[&_table]:w-full [&_table]:border-collapse [&_table]:my-2 [&_table]:text-caption " +
  "[&_th]:border-b [&_th]:border-rule [&_th]:bg-sheet-sunk [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-semibold " +
  "[&_td]:border-b [&_td]:border-rule [&_td]:px-2 [&_td]:py-1.5";

function AssistantMark() {
  return (
    <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-accent-tint text-accent" aria-hidden="true">
      <Sparkles className="size-3.5" />
    </div>
  );
}

function AssistantReply({ content, onRetry }: { content: string; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);
  const failed = content === ERROR_REPLY;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  return (
    <div className="group flex gap-2.5 animate-slide-up">
      <AssistantMark />
      <div className="min-w-0 flex-1">
        <div
          className={`rounded-lg rounded-tl-sm border px-3.5 py-2.5 text-body break-words ${
            failed ? "border-danger-soft bg-danger-tint text-danger" : "border-rule bg-sheet text-ink"
          }`}
        >
          {failed ? (
            content
          ) : (
            <div className={`overflow-x-auto ${MARKDOWN}`}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>
        <div className="mt-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {failed && onRetry ? (
            <button onClick={onRetry} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-caption text-ink-2 hover:bg-sheet-sunk hover:text-ink">
              <RotateCcw className="size-3" /> Try again
            </button>
          ) : !failed && (
            <button onClick={copy} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-caption text-ink-3 hover:bg-sheet-sunk hover:text-ink">
              {copied ? <Check className="size-3 text-done" /> : <Copy className="size-3" />}
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ChatDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => { scrollToBottom(); }, [messages, isLoading, streamingText]);

  // Grow the box with its text, up to about five lines.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [input]);

  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);

  const handleSend = async (text: string) => {
    if (!text.trim() || isLoading) return;
    setInput("");

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setIsLoading(true);
    setStreamingText("");

    try {
      // Stream the reply token by token; fall back to the plain endpoint.
      const result = await sendMessageStream(text, sessionId, (token) => {
        setStreamingText((prev) => prev + token);
      });
      setSessionId(result.session_id);
      setMessages((prev) => [...prev, { role: "assistant", content: result.full_reply }]);
    } catch {
      try {
        const res = await sendMessage(text, sessionId);
        setSessionId(res.session_id);
        const displayHistory = res.history.filter((m) => m.role === "user" || m.role === "assistant");
        setMessages(displayHistory);
      } catch {
        setMessages((prev) => [...prev, { role: "assistant", content: ERROR_REPLY }]);
      }
    } finally {
      setStreamingText("");
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  // Drop the failed reply and the question it answered, then ask again.
  const handleRetry = () => {
    const question = messages[messages.length - 2];
    if (!question || question.role !== "user") return;
    setMessages((prev) => prev.slice(0, -2));
    handleSend(question.content);
  };

  const handleClearChat = () => {
    setMessages([]);
    setSessionId(undefined);
    setInput("");
    inputRef.current?.focus();
  };

  const canSend = !isLoading && input.trim().length > 0;

  return (
    <Drawer open={open} onClose={onClose} title="Procurement Assistant" side="right">
      <div className="flex h-full flex-col bg-paper">

        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-rule bg-sheet px-4 py-2">
          <span className="flex items-center gap-2 text-caption text-ink-2">
            <span className="size-2 rounded-full bg-done" aria-hidden="true" />
            Answers from your procurement records
          </span>
          <button
            onClick={handleClearChat}
            disabled={messages.length === 0 || isLoading}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-caption font-medium text-ink-2 transition-colors hover:bg-sheet-sunk hover:text-ink disabled:pointer-events-none disabled:opacity-40"
            title="Start a new chat"
          >
            <MessageSquarePlus className="size-3.5" /> New chat
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5" role="log" aria-live="polite">
          {messages.length === 0 && (
            <div className="flex h-full flex-col justify-center animate-fade-in">
              <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-accent-tint text-accent">
                <Sparkles className="size-5" />
              </div>
              <p className="text-heading font-semibold text-ink">How can I help you today?</p>
              <p className="mb-5 mt-1 text-body text-ink-2">
                Ask about requests, contracts, vendors or licences, or start with one of these.
              </p>

              <div className="flex flex-col gap-2">
                {QUICK_PROMPTS.map(({ icon: Icon, text }) => (
                  <button
                    key={text}
                    onClick={() => handleSend(text)}
                    className="group flex items-center gap-3 rounded-md border border-rule bg-sheet px-3 py-2.5 text-left text-body text-ink transition-colors hover:border-accent-soft hover:bg-accent-tint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                  >
                    <span className="flex size-7 shrink-0 items-center justify-center rounded bg-sheet-sunk text-ink-2 transition-colors group-hover:bg-accent group-hover:text-white">
                      <Icon className="size-3.5" />
                    </span>
                    {text}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end animate-slide-up">
                <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-lg rounded-br-sm bg-accent px-3.5 py-2.5 text-body text-white">
                  {m.content}
                </div>
              </div>
            ) : (
              <AssistantReply
                key={i}
                content={m.content}
                onRetry={i === messages.length - 1 && !isLoading ? handleRetry : undefined}
              />
            )
          )}
          {isLoading && streamingText && (
            <div className="flex gap-2.5">
              <AssistantMark />
              <div className="min-w-0 flex-1 rounded-lg rounded-tl-sm border border-rule bg-sheet px-3.5 py-2.5 text-body text-ink break-words">
                <div className={`overflow-x-auto ${MARKDOWN}`}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingText}</ReactMarkdown>
                </div>
              </div>
            </div>
          )}
          {isLoading && !streamingText && (
            <div className="flex gap-2.5 animate-fade-in">
              <AssistantMark />
              <div className="flex items-center gap-1 rounded-lg rounded-tl-sm border border-rule bg-sheet px-3.5 py-3" aria-label="Assistant is thinking">
                {[0, 1, 2].map((d) => (
                  <span
                    key={d}
                    className="size-1.5 rounded-full bg-accent animate-pulse"
                    style={{ animationDelay: `${d * 200}ms` }}
                  />
                ))}
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="border-t border-rule bg-sheet px-4 pb-3 pt-3">
          <form
            onSubmit={(e) => { e.preventDefault(); handleSend(input); }}
            className="flex items-end gap-2 rounded-lg border border-rule-strong/60 bg-paper p-1.5 pl-3 transition-colors focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20"
          >
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  handleSend(input);
                }
              }}
              placeholder="Ask a question…"
              aria-label="Message"
              className="max-h-32 flex-1 resize-none bg-transparent py-1.5 text-body text-ink placeholder:text-ink-3 focus:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
            />
            <button
              type="submit"
              disabled={!canSend}
              aria-label="Send"
              className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-accent text-white transition-colors hover:bg-accent-hover disabled:bg-sheet-sunk disabled:text-ink-3"
            >
              <ArrowUp className="size-4" />
            </button>
          </form>
          <p className="mt-1.5 text-caption text-ink-3">Enter to send, Shift + Enter for a new line</p>
        </div>
      </div>
    </Drawer>
  );
}
