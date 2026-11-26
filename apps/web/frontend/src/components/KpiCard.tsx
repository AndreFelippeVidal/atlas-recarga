import type { Kpi, KpiMeasure } from "../api";
import { formatDelta, formatMeasure, MEASURE_LABELS, roundedDelta } from "../format";

interface Props {
  measure: KpiMeasure;
  kpi?: Kpi;
  previousMonthLabel?: string;
  // A consulta falhou: sem skeleton eterno; o banner de erro explica e oferece tentar de novo.
  failed?: boolean;
}

export default function KpiCard({ measure, kpi, previousMonthLabel, failed }: Props) {
  const label = MEASURE_LABELS[measure];
  if (!kpi && failed) {
    return (
      <div className="card" role="group" aria-label={`${label}: indisponível`}>
        <div className="card-label">{label}</div>
        <div className="card-value muted">—</div>
      </div>
    );
  }
  if (!kpi) {
    return (
      <div className="card skeleton" aria-busy="true" aria-label={`${label}: carregando`}>
        <div className="card-label">{label}</div>
        <div className="card-value">&nbsp;</div>
      </div>
    );
  }
  if (kpi.value === null) {
    return (
      <div className="card" role="group" aria-label={`${label}: sem recargas no recorte`}>
        <div className="card-label">{label}</div>
        <div className="card-value">—</div>
        <div className="card-delta flat">sem recargas no recorte</div>
      </div>
    );
  }
  const delta = kpi.delta_pct === null ? 0 : roundedDelta(kpi.delta_pct);
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
