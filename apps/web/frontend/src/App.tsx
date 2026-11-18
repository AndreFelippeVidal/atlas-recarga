import { useState } from "react";
import ErrorBanner from "./components/ErrorBanner";
import KpiCard from "./components/KpiCard";
import { formatMonth } from "./format";
import { useKpis, useMonths } from "./hooks";
import type { KpiMeasure } from "./api";

const MEASURES: KpiMeasure[] = ["gross_revenue", "recharge_count", "avg_ticket", "active_pos"];

export default function App() {
  const months = useMonths();
  const [chosen, setChosen] = useState<string | null>(null);
  // Padrão: último mês fechado (o mais recente da lista).
  const month = chosen ?? months.months[0] ?? null;
  const kpis = useKpis(month);
  const error = months.error ?? kpis.error;
  const retry = () => {
    if (months.error) months.retry();
    if (kpis.error) kpis.retry();
  };

  return (
    <div className="app">
      <header className="header">
        <h1>Atlas Recarga</h1>
        <label className="month-picker">
          Mês{" "}
          <select
            value={month ?? ""}
            disabled={months.months.length === 0}
            onChange={(e) => setChosen(e.target.value)}
          >
            {months.months.map((m) => (
              <option key={m} value={m}>
                {formatMonth(m)}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && <ErrorBanner code={error} onRetry={retry} />}

      <section className="kpis" aria-label="Indicadores do mês">
        {MEASURES.map((m) => (
          <KpiCard
            key={m}
            measure={m}
            kpi={kpis.kpis?.[m]}
            previousMonthLabel={kpis.kpis ? formatMonth(kpis.kpis.previous_month) : undefined}
          />
        ))}
      </section>

      <main className="content">
        <section className="map-area" aria-label="Mapa">
          <p className="placeholder">O mapa por região entra na P12.5.</p>
        </section>
        <aside className="side" aria-label="Ranking">
          <nav aria-label="Navegação do mapa" className="breadcrumb">
            Brasil
          </nav>
          <p className="placeholder">O ranking entra na P12.5.</p>
        </aside>
      </main>
    </div>
  );
}
