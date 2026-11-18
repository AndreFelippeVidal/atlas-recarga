import { act, render, screen, waitFor, within } from "@testing-library/react";
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

// Município: um quadrado com 3 municípios lado a lado (código IBGE como propriedade).
const MUN_TOPOLOGY = {
  type: "Topology",
  arcs: [SQUARE(0), SQUARE(10), SQUARE(20)],
  objects: {
    municipalities: {
      type: "GeometryCollection",
      geometries: [
        { type: "Polygon", arcs: [[0]], properties: { municipality_ibge_code: "1500001" } },
        { type: "Polygon", arcs: [[1]], properties: { municipality_ibge_code: "1500002" } },
        { type: "Polygon", arcs: [[2]], properties: { municipality_ibge_code: "1500003" } },
      ],
    },
  },
};
const MUNICIPALITIES = [
  { municipality_ibge_code: "1500002", municipality_name: "Alenquer", value: "50.00" },
  { municipality_ibge_code: "1500001", municipality_name: "Santarém", value: "10.00" },
];

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
    "/api/map/uf": () => json([{ uf: "PA", value: "300000.00" }]),
    "/api/map/municipality": () => json(MUNICIPALITIES),
    "/geo/br-uf.json": () => json(TOPOLOGY),
    "/geo/mun/PA.json": () => json(MUN_TOPOLOGY),
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
    const ranking = await screen.findByRole("list", { name: "Ranking: regiões" });
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
    await screen.findByRole("list", { name: "Ranking: regiões" });
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

describe("Drill-down", () => {
  const shapes = () => document.querySelectorAll("path.uf");

  it("clicar numa região mostra só as UFs dela e busca /api/map/uf", async () => {
    const fetchMock = mockFetch(route());
    render(<App />);
    expect(shapes()).toHaveLength(0);
    await userEvent.click(await screen.findByRole("button", { name: /PA, região Norte/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/map/uf?month=2026-10&measure=gross_revenue&region=N",
        expect.anything(),
      ),
    );
    expect(await screen.findByRole("list", { name: "Ranking: UFs da região" })).toBeVisible();
    expect(shapes()).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /SP/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "← Ver o Brasil inteiro" })).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Navegação do mapa" })).toHaveTextContent(
      "Brasil › Norte",
    );
  });

  it("clicar numa UF carrega os municípios e o botão volta ao Brasil inteiro", async () => {
    const fetchMock = mockFetch(route());
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /PA, região Norte/ }));
    await userEvent.click(await screen.findByRole("button", { name: /^PA: R\$\s300\.000,00/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/map/municipality?month=2026-10&measure=gross_revenue&uf=PA",
        expect.anything(),
      ),
    );
    expect(fetchMock).toHaveBeenCalledWith("/geo/mun/PA.json", expect.anything());
    expect(await screen.findByRole("list", { name: "Ranking: municípios da UF" })).toBeVisible();
    expect(shapes()).toHaveLength(3);
    // município sem recarga fica hachurado e é descrito como "sem recargas"
    expect(screen.getByRole("img", { name: "1500003: sem recargas" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "← Ver o Brasil inteiro" }));
    expect(await screen.findByRole("list", { name: "Ranking: regiões" })).toBeVisible();
    expect(shapes()).toHaveLength(2);
  });

  it("Esc sobe um nível por vez: município → UF → Brasil", async () => {
    mockFetch(route());
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /PA, região Norte/ }));
    await userEvent.click(await screen.findByRole("button", { name: /^PA: R\$\s300\.000,00/ }));
    await screen.findByRole("list", { name: "Ranking: municípios da UF" });
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByRole("list", { name: "Ranking: UFs da região" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByRole("list", { name: "Ranking: regiões" })).toBeVisible();
  });

  it("com mom_change, a maior queda do PA cai na classe mais baixa (critério 1)", async () => {
    mockFetch(
      route({
        "/api/map/region": () => json([{ region: "N", value: "-12.00" }]),
        "/api/map/uf": () => json([{ uf: "PA", value: "-12.00" }]),
        "/api/map/municipality": () =>
          json([
            { municipality_ibge_code: "1500001", municipality_name: "Santarém", value: "-40.00" },
            { municipality_ibge_code: "1500002", municipality_name: "Alenquer", value: "4.00" },
            { municipality_ibge_code: "1500003", municipality_name: "Óbidos", value: null },
          ]),
      }),
    );
    render(<App />);
    await screen.findByRole("list", { name: "Ranking: regiões" });
    await userEvent.selectOptions(screen.getByLabelText(/Medida/), "mom_change");
    await userEvent.click(await screen.findByRole("button", { name: /PA, região Norte: -12,00%/ }));
    await userEvent.click(await screen.findByRole("button", { name: /^PA: -12,00%/ }));
    const fall = await screen.findByRole("img", { name: "1500001: -40,00%" });
    expect((fall as unknown as SVGElement).style.fill).toBe("var(--div-1)");
    expect(
      (screen.getByRole("img", { name: "1500002: +4,00%" }) as unknown as SVGElement).style.fill,
    ).toBe("var(--div-3)");
    // sem base = sem valor: hachurado, nunca classe de queda
    expect(
      screen.getByRole("img", { name: "1500003: sem recargas" }).getAttribute("style"),
    ).toContain("#no-data");
  });
});

describe("Estados de carregamento e erro (P12.7)", () => {
  afterEach(() => vi.useRealTimers());

  it("mostra o skeleton do mapa e do ranking enquanto carrega", async () => {
    mockFetch(route({ "/api/map/region": () => new Promise<Response>(() => {}) }));
    render(<App />);
    expect(await screen.findByLabelText("Carregando o ranking")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.queryByText("Aquecendo o banco de dados…")).not.toBeInTheDocument();
  });

  it("depois de 3s de espera mostra 'Aquecendo o banco de dados…' e some ao chegar", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let release: (r: Response) => void = () => {};
    mockFetch(
      route({
        "/api/map/region": () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      }),
    );
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2900);
    });
    expect(screen.queryByText("Aquecendo o banco de dados…")).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(screen.getByText("Aquecendo o banco de dados…")).toBeInTheDocument();
    await act(async () => {
      release(json(REGIONS.gross_revenue));
    });
    expect(screen.queryByText("Aquecendo o banco de dados…")).not.toBeInTheDocument();
  });

  it("com erro, os KPIs não ficam em skeleton e o banner mantém o botão de tentar de novo", async () => {
    mockFetch(route({ "/api/kpis": () => down() }));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("WAREHOUSE_UNAVAILABLE");
    expect(screen.queryAllByLabelText(/carregando/)).toHaveLength(0);
    expect(screen.getAllByLabelText(/indisponível/)).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Tentar de novo" })).toBeVisible();
    // a página não quebra: o seletor de mês e o ranking continuam
    expect(screen.getByLabelText(/Mês/)).toBeVisible();
    expect(await screen.findByRole("list", { name: "Ranking: regiões" })).toBeVisible();
  });
});

describe("Escala divergente e acessibilidade (P12.7)", () => {
  const momRegions = () =>
    json([
      { region: "N", value: "-12.00" },
      { region: "SE", value: "12.00" },
    ]);

  it("mom_change usa a escala divergente: queda vermelha, alta azul, legenda com ±max", async () => {
    mockFetch(route({ "/api/map/region": momRegions }));
    render(<App />);
    await screen.findByRole("list", { name: "Ranking: regiões" });
    await userEvent.selectOptions(screen.getByLabelText(/Medida/), "mom_change");
    const pa = await screen.findByRole("button", { name: /PA, região Norte: -12,00%/ });
    const sp = screen.getByRole("button", { name: /SP, região Sudeste: \+12,00%/ });
    expect((pa as unknown as SVGElement).style.fill).toBe("var(--div-1)");
    expect((sp as unknown as SVGElement).style.fill).toBe("var(--div-5)");
    const legend = screen.getByRole("group", { name: /^Legenda/ });
    expect(legend).toHaveTextContent("Escala divergente centrada em 0%");
    expect(legend).toHaveTextContent("±12,00%");
    expect(legend).toHaveTextContent("maior queda");
    expect(legend).toHaveTextContent("maior alta");
  });

  it("o ranking de mom_change traz as 5 maiores altas e as 5 maiores quedas", async () => {
    const ufs = Array.from({ length: 14 }, (_, i) => ({
      uf: `U${i}`,
      value: String(7 - i), // 7, 6, ..., -6
    }));
    mockFetch(
      route({
        "/api/map/region": () => json([{ region: "N", value: "1.00" }]),
        "/api/map/uf": () => json(ufs),
      }),
    );
    render(<App />);
    await screen.findByRole("list", { name: "Ranking: regiões" });
    await userEvent.selectOptions(screen.getByLabelText(/Medida/), "mom_change");
    await userEvent.click(await screen.findByRole("button", { name: /PA, região Norte/ }));
    const list = await screen.findByRole("list", { name: "Ranking: UFs da região" });
    const names = within(list)
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label"));
    expect(names).toHaveLength(10);
    expect(names[0]).toContain("1º U0: +7,00%");
    expect(names[4]).toContain("5º U4: +3,00%");
    expect(names[5]).toContain("10º U9: -2,00%");
    expect(names[9]).toContain("14º U13: -6,00%");
  });

  it("navega por teclado: Tab chega ao polígono e Enter desce para a região", async () => {
    mockFetch(route());
    render(<App />);
    const pa = await screen.findByRole("button", { name: /PA, região Norte/ });
    expect(pa).toHaveAttribute("tabindex", "0");
    pa.focus();
    expect(pa).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("list", { name: "Ranking: UFs da região" })).toBeVisible();
  });

  it("anuncia o nível do mapa numa região de status", async () => {
    mockFetch(route());
    render(<App />);
    await screen.findByRole("list", { name: "Ranking: regiões" });
    expect(screen.getByText("Mapa do Brasil por região")).toHaveClass("sr-only");
    await userEvent.click(await screen.findByRole("button", { name: /PA, região Norte/ }));
    expect(await screen.findByText("Mapa da região por UF")).toHaveClass("sr-only");
  });

  it("o ranking é alcançável por Tab e Enter desce no nível", async () => {
    mockFetch(route());
    render(<App />);
    const ranking = await screen.findByRole("list", { name: "Ranking: regiões" });
    const first = within(ranking).getAllByRole("button")[0];
    first.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("list", { name: "Ranking: UFs da região" })).toBeVisible();
  });
});
