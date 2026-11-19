import { splitEvents } from "./chat";

describe("splitEvents", () => {
  it("separa eventos completos e guarda o resto", () => {
    const { events, rest } = splitEvents(
      'event: delta\ndata: {"text":"a"}\n\nevent: delta\ndata: {"te',
    );
    expect(events).toEqual([{ event: "delta", data: '{"text":"a"}' }]);
    expect(rest).toBe('event: delta\ndata: {"te');
  });

  it("ignora o ping (comentário SSE) e aceita CRLF", () => {
    const { events } = splitEvents(': ping\n\nevent: done\r\ndata: {"text":"ok"}\r\n\r\n');
    expect(events).toEqual([{ event: "done", data: '{"text":"ok"}' }]);
  });
});
