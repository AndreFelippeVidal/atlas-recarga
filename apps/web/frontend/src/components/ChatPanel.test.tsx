import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatPanel, { SUGGESTIONS } from "./ChatPanel";

const enc = new TextEncoder();
const sse = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

/** Resposta SSE controlada pelo teste: `push` manda um pedaço, `end` fecha o stream. */
function controlled() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => (controller = c) });
  return {
    response: new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    push: (text: string) => controller.enqueue(enc.encode(text)),
    end: () => controller.close(),
  };
}

const sent = (call: number) =>
  JSON.parse((vi.mocked(fetch).mock.calls[call][1] as RequestInit).body as string) as {
    message: string;
    conversation_id: string;
  };

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => vi.unstubAllGlobals());

async function openChat() {
  const user = userEvent.setup();
  render(<ChatPanel />);
  await user.click(screen.getByRole("button", { name: "Perguntar ao agente" }));
  return user;
}

it("abre vazio com as sugestões e fecha com Esc", async () => {
  const user = await openChat();
  for (const s of SUGGESTIONS) expect(screen.getByRole("button", { name: s })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("log")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Perguntar ao agente" })).toHaveFocus();
});

it("acrescenta os delta e troca pelo done, com a Fonte como veio", async () => {
  const stream = controlled();
  vi.mocked(fetch).mockResolvedValue(stream.response);
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "receita de outubro?{Enter}");

  expect(screen.getByRole("button", { name: "Parar" })).toBeInTheDocument();
  stream.push(sse("delta", { text: "A receita foi de R$ 4.122" }));
  await screen.findByText("A receita foi de R$ 4.122");
  stream.push(sse("delta", { text: ".460,00." }));
  await screen.findByText("A receita foi de R$ 4.122.460,00.");

  const final = "A receita foi de R$ 4.122.460,00.\nFonte: semantic.mv_recharges · gross_revenue";
  stream.push(": ping\n\n" + sse("done", { text: final }));
  stream.end();
  const answer = await screen.findByText(
    (_, el) => el?.className === "chat-answer" && el.textContent === final,
  );
  expect(answer).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled(); // campo vazio
  expect(sent(0).message).toBe("receita de outubro?");
  expect(sent(0).conversation_id).toBeTruthy();
});

it("Shift+Enter quebra a linha e não envia", async () => {
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "a{Shift>}{Enter}{/Shift}b");
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Sua pergunta")).toHaveValue("a\nb");
});

it("a mesma conversa vai em todas as perguntas", async () => {
  vi.mocked(fetch).mockImplementation(() => {
    const s = controlled();
    s.push(sse("done", { text: "ok" }));
    s.end();
    return Promise.resolve(s.response);
  });
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "um{Enter}");
  await screen.findByText("ok");
  await user.type(screen.getByLabelText("Sua pergunta"), "dois{Enter}");
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(sent(1).conversation_id).toBe(sent(0).conversation_id);
});

it("Parar aborta a conexão e mantém o texto parcial", async () => {
  const stream = controlled();
  vi.mocked(fetch).mockImplementation((_url, init) => {
    (init as RequestInit).signal?.addEventListener("abort", () => stream.push(""));
    return Promise.resolve(stream.response);
  });
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "oi{Enter}");
  stream.push(sse("delta", { text: "A rec" }));
  await screen.findByText("A rec");
  await user.click(screen.getByRole("button", { name: "Parar" }));
  const signal = (vi.mocked(fetch).mock.calls[0][1] as RequestInit).signal as AbortSignal;
  expect(signal.aborted).toBe(true);
});

it.each([
  [429, "RATE_LIMITED", "Limite de uso atingido, tente em 1 minuto."],
  [503, "AGENT_UNAVAILABLE", "O agente está parado ou indisponível."],
  [403, "PERMISSION_DENIED", "Você não tem acesso ao agente."],
])("HTTP %i vira a mensagem do §4 e oferece tentar de novo", async (status, code, text) => {
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ detail: { code, message: "x" } }), { status }),
  );
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "oi{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent(text);

  const stream = controlled();
  vi.mocked(fetch).mockResolvedValue(stream.response);
  stream.push(sse("done", { text: "agora foi" }));
  stream.end();
  await user.click(screen.getByRole("button", { name: "Tentar de novo" }));
  expect(await screen.findByText("agora foi")).toBeInTheDocument();
  expect(sent(1).message).toBe("oi");
});

it("evento error no meio do stream mostra o erro por código e mantém o parcial", async () => {
  const stream = controlled();
  vi.mocked(fetch).mockResolvedValue(stream.response);
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "oi{Enter}");
  stream.push(sse("delta", { text: "A rec" }) + sse("error", { code: "TIMEOUT", message: "x" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("O agente demorou demais");
  expect(screen.getByText("A rec")).toBeInTheDocument();
});

it("stream cortado sem done vira erro, sem inventar resposta", async () => {
  const stream = controlled();
  vi.mocked(fetch).mockResolvedValue(stream.response);
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "oi{Enter}");
  stream.push(sse("delta", { text: "A rec" }));
  stream.end();
  expect(await screen.findByRole("alert")).toHaveTextContent("AGENT_ERROR");
});

it("sem rede mostra o erro e o resto da página segue", async () => {
  vi.mocked(fetch).mockRejectedValue(new TypeError("fetch failed"));
  const user = await openChat();
  await user.type(screen.getByLabelText("Sua pergunta"), "oi{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("NETWORK_ERROR");
});

it("não envia pergunta vazia e limita o tamanho no campo", async () => {
  const user = await openChat();
  await user.click(screen.getByLabelText("Sua pergunta"));
  await user.keyboard("{Enter}");
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Sua pergunta")).toHaveAttribute("maxlength", "2000");
});
