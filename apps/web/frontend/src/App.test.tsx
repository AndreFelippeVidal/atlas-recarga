import { render, screen, waitFor } from "@testing-library/react";
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

function mockFetch(handler: (url: string) => Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => Promise.resolve(handler(url))),
  );
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("mostra skeleton e depois os 4 KPI cards do último mês", async () => {
    mockFetch((url) =>
      url.startsWith("/api/months") ? json({ months: ["2026-10", "2026-09"] }) : json(KPIS),
    );
    render(<App />);
    expect(screen.getAllByLabelText(/carregando/)).toHaveLength(4);
    expect(await screen.findByText(/4\.122\.460,00/)).toBeInTheDocument();
    expect(screen.getByText("150.000")).toBeInTheDocument();
    expect(screen.getByText("+5,70%")).toBeInTheDocument();
    expect(screen.getByText("-6,25%")).toBeInTheDocument();
    expect(screen.getByText("sem base")).toBeInTheDocument();
  });

  it("troca o mês e busca os KPIs do mês escolhido", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.startsWith("/api/months") ? json({ months: ["2026-10", "2026-09"] }) : json(KPIS),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await screen.findByText(/4\.122\.460,00/);
    await userEvent.selectOptions(screen.getByRole("combobox"), "2026-09");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/kpis?month=2026-09", expect.anything()),
    );
  });

  it("mostra o banner de erro com o código e tenta de novo", async () => {
    let fail = true;
    mockFetch((url) => {
      if (url.startsWith("/api/months")) return json({ months: ["2026-10"] });
      return fail
        ? json({ detail: { code: "WAREHOUSE_UNAVAILABLE", message: "x" } }, 503)
        : json(KPIS);
    });
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
    expect(await screen.findByRole("alert")).toHaveTextContent("NETWORK_ERROR");
  });
});
