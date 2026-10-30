import { api } from "./client";
import { getAccessToken } from "./client";

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
}

export interface ChatResponse {
  session_id: string;
  message: string;
  history: ChatMessage[];
}

export async function sendMessage(message: string, sessionId?: string): Promise<ChatResponse> {
  const response = await api.post<any>("/chat/", {
    message,
    session_id: sessionId || null,
  });
  
  // client.ts unwraps the { data: ... } envelope for us if it exists,
  // but if the backend didn't wrap it, it just returns the raw object.
  // We handle both safely here:
  const data = response.data || response;
  
  if (!data.history) {
      console.error("Malformed response from server:", data);
      throw new Error("Malformed response");
  }
  
  return data;
}

/**
 * Stream the assistant reply token-by-token via Server-Sent Events.
 *
 * Calls `onToken` for every token fragment so the UI can display a
 * typing effect.  Returns the full reply text and session_id when the
 * stream finishes.
 */
export async function sendMessageStream(
  message: string,
  sessionId: string | undefined,
  onToken: (token: string) => void,
): Promise<{ session_id: string; full_reply: string }> {
  const token = getAccessToken();
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message, session_id: sessionId || null }),
  });

  if (!res.ok) {
    throw new Error(`Stream request failed: ${res.status}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sessionIdResult = sessionId || "";
  let fullReply = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE lines are separated by double newlines
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        const payload = JSON.parse(line.slice(6));
        if (payload.done) {
          fullReply = payload.full_reply || fullReply;
          sessionIdResult = payload.session_id || sessionIdResult;
        } else if (payload.token) {
          onToken(payload.token);
        }
      } catch {
        // skip malformed SSE lines
      }
    }
  }

  return { session_id: sessionIdResult, full_reply: fullReply || "I could not generate a response." };
}

