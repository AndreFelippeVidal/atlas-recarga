import { useState } from "react";
import ErrorBanner from "./components/ErrorBanner";
import KpiCard from "./components/KpiCard";
import MapPanel from "./components/MapPanel";
import { formatMonth, MEASURE_LABELS } from "./format";
import { useKpis, useMonths } from "./hooks";
import type { KpiMeasure, MapMeasure } from "./api";

const MEASURES: KpiMeasure[] = ["gross_revenue", "recharge_count", "avg_ticket", "active_pos"];
const MAP_MEASURES: MapMeasure[] = [...MEASURES, "mom_change"];

export default function App() {
  const months = useMonths();
  const [chosen, setChosen] = useState<string | null>(null);
  const [measure, setMeasure] = useState<MapMeasure>("gross_revenue");
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
        <div className="pickers">
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
          <label className="month-picker">
            Medida{" "}
            <select value={measure} onChange={(e) => setMeasure(e.target.value as MapMeasure)}>
              {MAP_MEASURES.map((m) => (
                <option key={m} value={m}>
                  {MEASURE_LABELS[m]}
                </option>
              ))}
            </select>
          </label>
        </div>
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
        <MapPanel month={month} measure={measure} />
      </main>
    </div>
  );
}
