import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const kpi = (value: string, previous: string | null, delta: string | null) => ({
  value,
  previous,
  delta_pct: delta,
});
const KPIS = {
  month: "2026-10",
  previous_month: "2026-09",
  gross_revenue: kpi("4122460.00", "3900000.00", "5.70"),
  recharge_count: kpi("150000", "160000", "-6.25"),
  avg_ticket: kpi("27.48", "24.37", "12.76"),
  active_pos: kpi("4798", null, null),
};

// Duas UFs em quadrados separados, uma no Norte e outra no Sudeste (TopoJSON sem quantização).
const SQUARE = (x: number) => [
  [x, 0],
  [x + 10, 0],
  [x + 10, 10],
  [x, 10],
  [x, 0],
];
const TOPOLOGY = {
  type: "Topology",
  arcs: [SQUARE(0), SQUARE(20)],
  objects: {
    uf: {
      type: "GeometryCollection",
      geometries: [
        { type: "Polygon", arcs: [[0]], properties: { uf: "PA", region: "N" } },
        { type: "Polygon", arcs: [[1]], properties: { uf: "SP", region: "SE" } },
      ],
    },
  },
};

const REGIONS = {
  gross_revenue: [
    { region: "SE", value: "2500000.00" },
    { region: "N", value: "300000.00" },
  ],
  recharge_count: [
    { region: "SE", value: "90000" },
    { region: "N", value: "12000" },
  ],
};

type Handler = (url: string) => Response | Promise<Response>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const down = () => json({ detail: { code: "WAREHOUSE_UNAVAILABLE", message: "x" } }, 503);

function route(overrides: Record<string, Handler> = {}): Handler {
  const base: Record<string, Handler> = {
    "/api/months": () => json({ months: ["2026-10", "2026-09"] }),
    "/api/kpis": () => json(KPIS),
    "/api/map/region": (url) => {
      const measure = new URL(url, "http://x").searchParams.get("measure") as keyof typeof REGIONS;
      return json(REGIONS[measure]);
    },
    "/geo/br-uf.json": () => json(TOPOLOGY),
  };
  const all = { ...base, ...overrides };
  return (url) => {
    const path = new URL(url, "http://x").pathname;
    return all[path]?.(url) ?? json({}, 404);
  };
}

function mockFetch(handler: Handler) {
  const fetchMock = vi.fn((url: string) => Promise.resolve(handler(url)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("mostra skeleton e depois os 4 KPI cards do último mês", async () => {
    mockFetch(route());
    render(<App />);
    expect(screen.getAllByLabelText(/carregando/)).toHaveLength(4);
    expect(await screen.findByText(/4\.122\.460,00/)).toBeInTheDocument();
    expect(screen.getByText("150.000")).toBeInTheDocument();
    expect(screen.getByText("+5,70%")).toBeInTheDocument();
    expect(screen.getByText("-6,25%")).toBeInTheDocument();
    expect(screen.getByText("sem base")).toBeInTheDocument();
  });

  it("troca o mês e busca os KPIs do mês escolhido", async () => {
    const fetchMock = mockFetch(route());
    render(<App />);
    await screen.findByText(/4\.122\.460,00/);
    await userEvent.selectOptions(screen.getByLabelText(/Mês/), "2026-09");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/kpis?month=2026-09", expect.anything()),
    );
  });

  it("mostra o banner de erro com o código e tenta de novo", async () => {
    let fail = true;
    mockFetch(route({ "/api/kpis": () => (fail ? down() : json(KPIS)) }));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Não foi possível carregar os dados (WAREHOUSE_UNAVAILABLE)",
    );
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText(/4\.122\.460,00/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("não quebra com a API fora do ar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("offline"))),
    );
    render(<App />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("NETWORK_ERROR");
  });
});

describe("Mapa por região", () => {
  it("pinta as UFs pela região, com legenda e ranking que repetem o valor", async () => {
    mockFetch(route());
    render(<App />);
    const ranking = await screen.findByRole("list", { name: "Ranking das regiões" });
    expect(
      within(ranking).getByRole("button", { name: /1º Sudeste: R\$\s2\.500\.000,00/ }),
    ).toBeVisible();
    expect(
      within(ranking).getByRole("button", { name: /2º Norte: R\$\s300\.000,00/ }),
    ).toBeVisible();
    // "sem recargas" para as regiões que a API não devolveu
    expect(within(ranking).getByText("Nordeste: sem recargas")).toBeInTheDocument();
    // cada UF é um botão com nome e valor, e a cor nunca é a única informação
    expect(
      screen.getByRole("button", { name: /SP, região Sudeste: R\$\s2\.500\.000,00/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PA, região Norte/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Legenda/)).toHaveTextContent("Classes por quantis (R$)");
    expect(screen.getByLabelText(/^Legenda/)).toHaveTextContent("sem recargas");
  });

  it("mostra o tooltip com nome, valor e posição ao passar o mouse", async () => {
    mockFetch(route());
    render(<App />);
    const sp = await screen.findByRole("button", { name: /SP, região Sudeste/ });
    await userEvent.hover(sp);
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("Sudeste");
    expect(tip).toHaveTextContent("1º de 2");
  });

  it("recolore e busca de novo ao trocar a medida", async () => {
    const fetchMock = mockFetch(route());
    render(<App />);
    await screen.findByRole("list", { name: "Ranking das regiões" });
    await userEvent.selectOptions(screen.getByLabelText(/Medida/), "recharge_count");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/map/region?month=2026-10&measure=recharge_count",
        expect.anything(),
      ),
    );
    expect(await screen.findByRole("button", { name: /1º Sudeste: 90\.000/ })).toBeVisible();
    expect(screen.getByLabelText(/^Legenda/)).toHaveTextContent("recargas");
  });

  it("mantém o mapa anterior, com a medida dele, quando a nova consulta falha", async () => {
    mockFetch(
      route({
        "/api/map/region": (url) =>
          url.includes("measure=gross_revenue") ? json(REGIONS.gross_revenue) : down(),
      }),
    );
    render(<App />);
    await screen.findByRole("button", { name: /1º Sudeste: R\$\s2\.500\.000,00/ });
    await userEvent.selectOptions(screen.getByLabelText(/Medida/), "recharge_count");
    expect(await screen.findByRole("alert")).toHaveTextContent("WAREHOUSE_UNAVAILABLE");
    expect(screen.getByRole("button", { name: /1º Sudeste: R\$\s2\.500\.000,00/ })).toBeVisible();
  });
});
