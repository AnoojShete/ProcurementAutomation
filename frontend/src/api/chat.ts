import { api } from "./client";

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
