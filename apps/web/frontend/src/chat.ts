import { ApiError } from "./api";

// Cliente do `POST /api/chat` (SPEC-007 §3, ADR-0023): SSE com `delta`, `done` e `error`.
// O texto vem do agente e é exibido como veio; nada aqui calcula ou reformata número.

export interface ChatHandlers {
  onDelta: (text: string) => void;
  onDone: (text: string) => void;
}

interface SseEvent {
  event: string;
  data: string;
}

/** Separa o buffer em eventos completos (terminados por linha em branco); ignora `: ping`. */
export function splitEvents(buffer: string): { events: SseEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: SseEvent[] = [];
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue; // comentário (ping)
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length > 0) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

async function httpError(res: Response): Promise<ApiError> {
  let code = `HTTP_${res.status}`;
  let message = res.statusText;
  try {
    const body = (await res.json()) as { detail?: { code?: string; message?: string } };
    code = body.detail?.code ?? code;
    message = body.detail?.message ?? message;
  } catch {
    // corpo sem JSON: fica o código HTTP
  }
  return new ApiError(code, message);
}

function payload(data: string): { text?: string; code?: string; message?: string } {
  try {
    return JSON.parse(data) as { text?: string; code?: string; message?: string };
  } catch {
    return {};
  }
}

/** Envia a pergunta e acompanha o stream. Termina com `onDone`, ou lança `ApiError`/`AbortError`. */
export async function streamChat(
  message: string,
  conversationId: string,
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message, conversation_id: conversationId }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("NETWORK_ERROR", "API fora do ar");
  }
  if (!res.ok) throw await httpError(res);
  if (!res.body) throw new ApiError("AGENT_ERROR", "resposta sem corpo");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") throw err;
        throw new ApiError("AGENT_UNAVAILABLE", "a conexão caiu no meio");
      }
      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      const { events, rest } = splitEvents(chunk.done ? buffer + "\n\n" : buffer);
      buffer = rest;
      for (const { event, data } of events) {
        const body = payload(data);
        if (event === "delta") handlers.onDelta(body.text ?? "");
        else if (event === "done") {
          handlers.onDone(body.text ?? "");
          return;
        } else if (event === "error") {
          throw new ApiError(body.code ?? "AGENT_ERROR", body.message ?? "erro do agente");
        }
      }
      if (chunk.done) throw new ApiError("AGENT_ERROR", "o agente encerrou sem resposta");
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}

export const CHAT_ERRORS: Record<string, string> = {
  RATE_LIMITED: "Limite de uso atingido, tente em 1 minuto.",
  AGENT_UNAVAILABLE: "O agente está parado ou indisponível.",
  PERMISSION_DENIED: "Você não tem acesso ao agente.",
  TIMEOUT: "O agente demorou demais para responder.",
};

export function chatErrorMessage(code: string): string {
  return CHAT_ERRORS[code] ?? `Não foi possível obter a resposta (${code}).`;
}
