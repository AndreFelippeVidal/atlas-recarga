import type { Kpi, KpiMeasure } from "../api";
import { formatDelta, formatMeasure } from "../format";

export const KPI_LABELS: Record<KpiMeasure, string> = {
  gross_revenue: "Receita bruta",
  recharge_count: "Recargas",
  avg_ticket: "Ticket médio",
  active_pos: "PDVs ativos",
};

interface Props {
  measure: KpiMeasure;
  kpi?: Kpi;
  previousMonthLabel?: string;
}

export default function KpiCard({ measure, kpi, previousMonthLabel }: Props) {
  const label = KPI_LABELS[measure];
  if (!kpi) {
    return (
      <div className="card skeleton" aria-busy="true" aria-label={`${label}: carregando`}>
        <div className="card-label">{label}</div>
        <div className="card-value">&nbsp;</div>
      </div>
    );
  }
  const delta = kpi.delta_pct === null ? 0 : Number(kpi.delta_pct);
  // A informação não depende só da cor: o sinal e a seta repetem o sentido.
  const trend = kpi.delta_pct === null ? "flat" : delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : "■";
  return (
    <div className="card" role="group" aria-label={label}>
      <div className="card-label">{label}</div>
      <div className="card-value">{formatMeasure(measure, kpi.value)}</div>
      <div className={`card-delta ${trend}`}>
        <span aria-hidden="true">{arrow}</span> {formatDelta(kpi.delta_pct)}
        {kpi.previous !== null && (
          <span className="card-prev">
            {" "}
            vs {previousMonthLabel}: {formatMeasure(measure, kpi.previous)}
          </span>
        )}
      </div>
    </div>
  );
}
