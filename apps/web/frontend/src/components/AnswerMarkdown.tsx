import type { ComponentProps } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Renderiza o Markdown da resposta do agente (ADR-0024). A resposta vem de um LLM, então é entrada
// não confiável: HTML cru é descartado, só uma lista fechada de elementos passa, imagens nunca, e
// links só valem em http(s). Não calcula nem reformata número: só muda a forma do texto.

const ALLOWED = [
  "p",
  "br",
  "hr",
  "strong",
  "em",
  "del",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
  "blockquote",
  "h1",
  "h2",
  "h3",
  "h4",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "a",
];

const safeUrl = (url: string): string => (/^https?:\/\//i.test(url) ? url : "");

const components: ComponentProps<typeof Markdown>["components"] = {
  // Títulos do agente viram h4: o painel já tem o seu h2.
  h1: "h4",
  h2: "h4",
  h3: "h4",
  a: ({ href, children }) =>
    href ? (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  table: ({ children }) => (
    <div className="md-table">
      <table>{children}</table>
    </div>
  ),
};

/** Separa o bloco final `Fonte:` do corpo, só para mostrá-lo como citação. O texto não muda. */
export function splitSource(text: string): { body: string; source: string } {
  const matches = [...text.matchAll(/(^|\n)[ \t]*(?:\*\*)?Fonte:/g)];
  const last = matches.at(-1);
  if (last?.index === undefined) return { body: text, source: "" };
  const start = last.index + last[1].length;
  return { body: text.slice(0, start).trimEnd(), source: text.slice(start).trim() };
}

function Rich({ children, inline }: { children: string; inline?: boolean }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      allowedElements={ALLOWED}
      unwrapDisallowed
      urlTransform={safeUrl}
      components={inline ? { ...components, p: ({ children: c }) => <>{c}</> } : components}
    >
      {children}
    </Markdown>
  );
}

export default function AnswerMarkdown({ text }: { text: string }) {
  const { body, source } = splitSource(text);
  // O rótulo "Fonte:" é sempre mostrado em negrito; o resto da citação também aceita Markdown.
  const rest = source.replace(/^(?:\*\*)?Fonte:(?:\*\*)?/, "");
  return (
    <div className="md">
      {body !== "" && <Rich>{body}</Rich>}
      {source !== "" && (
        <aside className="md-source" aria-label="Fonte da resposta">
          <strong>Fonte:</strong> <Rich inline>{rest.trim()}</Rich>
        </aside>
      )}
    </div>
  );
}
