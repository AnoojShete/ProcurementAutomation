import { useState, useRef, useEffect } from "react";
import { Drawer } from "./Drawer";
import { sendMessage, type ChatMessage } from "@/api/chat";
import { Send, Bot, Loader2, MessageSquarePlus } from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const QUICK_PROMPTS = [
  "What is our procurement summary?",
  "Show my pending purchase requests",
  "Are there any SaaS license anomalies?",
  "Check risk score for Acme Corp"
];

export function ChatDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => { scrollToBottom(); }, [messages, isLoading]);

  const handleSend = async (text: string) => {
    if (!text.trim() || isLoading) return;
    setInput("");
    
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setIsLoading(true);

    try {
      const res = await sendMessage(text, sessionId);
      setSessionId(res.session_id);
      
      const displayHistory = res.history.filter((m) => m.role === "user" || m.role === "assistant");
      setMessages(displayHistory);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: "Sorry, I encountered an error connecting to the AI." }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearChat = () => {
    setMessages([]);
    setSessionId(undefined);
    setInput("");
  };

  return (
    <Drawer open={open} onClose={onClose} title="Procurement Assistant AI" side="right">
      <div className="flex flex-col h-[calc(100vh-60px)] bg-slate-50 relative">
        
        {/* Header Actions */}
        <div className="absolute top-0 right-4 p-2 z-10">
          {messages.length > 0 && (
            <button 
              onClick={handleClearChat}
              className="text-slate-400 hover:text-blue-600 transition-colors flex items-center text-xs font-medium bg-white px-2 py-1 rounded-md shadow-sm border border-slate-200"
              title="Start New Chat"
            >
              <MessageSquarePlus className="w-4 h-4 mr-1" /> New Chat
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 pt-12">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-slate-500">
              <Bot className="h-12 w-12 text-blue-200 mb-4" />
              <p className="text-sm font-medium mb-6 text-slate-600">How can I help you today?</p>
              
              <div className="flex flex-col gap-2 w-full max-w-xs">
                {QUICK_PROMPTS.map((prompt, i) => (
                  <button
                    key={i}
                    onClick={() => handleSend(prompt)}
                    className="text-left px-4 py-2 rounded-xl bg-white border border-slate-200 text-xs text-slate-600 hover:border-blue-300 hover:bg-blue-50 transition-all shadow-sm"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}
          
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${
                  m.role === "user" 
                    ? "bg-blue-600 text-white rounded-br-none" 
                    : "bg-white border border-slate-200 text-slate-800 rounded-bl-none shadow-sm overflow-x-auto"
                }`}
              >
                {m.role === "user" ? (
                  m.content
                ) : (
                  <div className="[&>p]:mb-2 last:[&>p]:mb-0 [&>ul]:list-disc [&>ul]:ml-5 [&>ul]:mb-2 [&>ol]:list-decimal [&>ol]:ml-5 [&>ol]:mb-2 [&>table]:w-full [&>table]:border-collapse [&>table]:mb-2 [&th]:border [&th]:border-slate-300 [&th]:px-2 [&th]:py-1 [&th]:bg-slate-100 [&td]:border [&td]:border-slate-200 [&td]:px-2 [&td]:py-1 [&strong]:font-semibold">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {m.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-white border border-slate-200 text-slate-500 rounded-2xl rounded-bl-none px-4 py-3 shadow-sm flex items-center text-sm">
                <Loader2 className="h-4 w-4 animate-spin mr-2 text-blue-500" /> Thinking...
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="p-4 bg-white border-t border-slate-200 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
          <form onSubmit={(e) => { e.preventDefault(); handleSend(input); }} className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question..."
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="inline-flex items-center justify-center rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>
    </Drawer>
  );
}
