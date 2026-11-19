import { useEffect, useRef, useState } from "react";
import { chatErrorMessage, streamChat } from "../chat";
import { ApiError } from "../api";
import AnswerMarkdown from "./AnswerMarkdown";

// Painel de chat (SPEC-007 §4). Renderiza o Markdown do agente (ADR-0024) e destaca o bloco
// `Fonte:`: o frontend não calcula, soma nem reformata número, e não mexe no mapa nem nos KPIs.

export const SUGGESTIONS = [
  "Qual a receita bruta do último mês?",
  "Qual a UF com maior receita no último mês?",
  "Como foi a variação de receita contra o mês anterior?",
];
const MAX_CHARS = 2000;

interface Turn {
  id: number;
  question: string;
  answer: string;
  status: "streaming" | "done" | "stopped" | "error";
  error?: string;
}

function newConversationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `c-${Date.now()}-${Math.floor(performance.now())}`;
}

function ChatIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.5-4.6A8 8 0 1 1 21 12Z" />
    </svg>
  );
}

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const conversationId = useRef(newConversationId());
  const abort = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const openerRef = useRef<HTMLButtonElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const busy = turns.at(-1)?.status === "streaming";

  useEffect(() => () => abort.current?.abort(), []);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) inputRef.current?.focus();
    else if (wasOpen.current) openerRef.current?.focus(); // devolve o foco ao fechar
    wasOpen.current = open;
  }, [open]);
  useEffect(() => {
    logRef.current?.scrollTo?.({ top: logRef.current.scrollHeight });
  }, [turns]);

  const patch = (id: number, change: Partial<Turn>) =>
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...change } : t)));

  const send = async (raw: string, replaceId?: number) => {
    const question = raw.trim();
    if (!question || busy) return;
    const id = replaceId ?? nextId.current++;
    const turn: Turn = { id, question, answer: "", status: "streaming" };
    setTurns((all) => (replaceId ? all.map((t) => (t.id === id ? turn : t)) : [...all, turn]));
    setInput("");
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamChat(
        question,
        conversationId.current,
        {
          // `delta` acrescenta; `done` troca pelo texto final (já mascarado pelo agente).
          onDelta: (text) =>
            setTurns((all) =>
              all.map((t) => (t.id === id ? { ...t, answer: t.answer + text } : t)),
            ),
          onDone: (text) => patch(id, { answer: text, status: "done" }),
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        patch(id, { status: "stopped" });
      } else {
        const code = err instanceof ApiError ? err.code : "AGENT_ERROR";
        patch(id, { status: "error", error: chatErrorMessage(code) });
      }
    } finally {
      if (abort.current === controller) abort.current = null;
    }
  };

  const close = () => {
    setOpen(false);
  };

  if (!open) {
    return (
      <button ref={openerRef} type="button" className="chat-open" onClick={() => setOpen(true)}>
        <ChatIcon />
        Perguntar ao agente
      </button>
    );
  }

  return (
    <section
      className="chat"
      aria-label="Chat com o agente"
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
      }}
    >
      <header className="chat-head">
        <span className="chat-avatar" aria-hidden="true">
          <ChatIcon />
        </span>
        <div className="chat-title">
          <h2>Perguntar ao agente</h2>
          <p>Respostas só das métricas oficiais</p>
        </div>
        <button type="button" className="chat-close" onClick={close} aria-label="Fechar o chat">
          <span aria-hidden="true">×</span>
        </button>
      </header>

      <div className="chat-log" ref={logRef} role="log" aria-live="polite">
        {turns.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty-title">Pergunte sobre receita, recargas e comissão</p>
            <p className="chat-empty-sub">Algumas ideias para começar:</p>
            <ul>
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button type="button" className="chat-suggestion" onClick={() => void send(s)}>
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((t) => (
          <div key={t.id} className="chat-turn">
            <p className="chat-question">{t.question}</p>
            {t.status === "streaming" && t.answer === "" && (
              <p className="chat-wait" role="status">
                <span className="chat-dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                Consultando o agente
              </p>
            )}
            {t.answer !== "" && (
              <div className={`chat-answer${t.status === "streaming" ? " streaming" : ""}`}>
                <AnswerMarkdown text={t.answer} />
              </div>
            )}
            {t.status === "stopped" && <p className="chat-note">Resposta interrompida.</p>}
            {t.status === "error" && (
              <div className="chat-error" role="alert">
                <span>{t.error}</span>
                <button type="button" onClick={() => void send(t.question, t.id)} disabled={busy}>
                  Tentar de novo
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <textarea
          ref={inputRef}
          aria-label="Sua pergunta"
          value={input}
          maxLength={MAX_CHARS}
          rows={2}
          placeholder="Escreva e aperte Enter (Shift+Enter quebra a linha)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send(input);
            }
          }}
        />
        {busy ? (
          <button type="button" onClick={() => abort.current?.abort()}>
            Parar
          </button>
        ) : (
          <button type="submit" disabled={input.trim() === ""}>
            Enviar
          </button>
        )}
      </form>
    </section>
  );
}
