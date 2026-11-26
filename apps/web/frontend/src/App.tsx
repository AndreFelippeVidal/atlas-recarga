import { useMemo, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import ErrorBanner from "./components/ErrorBanner";
import KpiCard from "./components/KpiCard";
import MapPanel from "./components/MapPanel";
import { formatMonth, MEASURE_LABELS, posTypeLabel } from "./format";
import { useFilterOptions, useKpis, useMonths } from "./hooks";
import type { Filters, KpiMeasure, MapMeasure } from "./api";

const MEASURES: KpiMeasure[] = ["gross_revenue", "recharge_count", "avg_ticket", "active_pos"];
const MAP_MEASURES: MapMeasure[] = [...MEASURES, "mom_change"];

export default function App() {
  const months = useMonths();
  const [chosen, setChosen] = useState<string | null>(null);
  const [measure, setMeasure] = useState<MapMeasure>("gross_revenue");
  // Padrão: último mês fechado (o mais recente da lista).
  const month = chosen ?? months.months[0] ?? null;
  // Filtros só em memória (SPEC-007 §4); "" = Todos.
  const [posType, setPosType] = useState("");
  const [distributor, setDistributor] = useState("");
  const filters = useMemo<Filters>(
    () => ({ pos_type: posType || undefined, distributor: distributor || undefined }),
    [posType, distributor],
  );
  const filterOptions = useFilterOptions();
  const kpis = useKpis(month, filters);
  const error = months.error ?? kpis.error ?? filterOptions.error;
  const retry = () => {
    if (months.error) months.retry();
    if (kpis.error) kpis.retry();
    if (filterOptions.error) filterOptions.retry();
  };
  const clearFilters = () => {
    setPosType("");
    setDistributor("");
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
          <label className="month-picker">
            Tipo de PDV{" "}
            <select
              value={posType}
              disabled={!filterOptions.options}
              onChange={(e) => setPosType(e.target.value)}
            >
              <option value="">Todos</option>
              {(filterOptions.options?.pos_types ?? []).map((t) => (
                <option key={t} value={t}>
                  {posTypeLabel(t)}
                </option>
              ))}
            </select>
          </label>
          <label className="month-picker">
            Distribuidor{" "}
            <select
              value={distributor}
              disabled={!filterOptions.options}
              onChange={(e) => setDistributor(e.target.value)}
            >
              <option value="">Todos</option>
              {(filterOptions.options?.distributors ?? []).map((d) => (
                <option key={d} value={d}>
                  {d}
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
            failed={error !== null}
          />
        ))}
      </section>

      <main className="content">
        <MapPanel
          month={month}
          measure={measure}
          monthLoading={months.loading}
          filters={filters}
          onClearFilters={clearFilters}
        />
      </main>

      <ChatPanel />
    </div>
  );
}
