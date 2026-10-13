import client from "./client";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  session_id: string;
  message: string;
  history: ChatMessage[];
}

export async function sendMessage(message: string, sessionId?: string): Promise<ChatResponse> {
  const response = await client.post("/api/chat/", {
    message,
    session_id: sessionId || null,
  });
  return response.data;
}