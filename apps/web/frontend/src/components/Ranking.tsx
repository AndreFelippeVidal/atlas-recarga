import type { MapMeasure } from "../api";
import { formatMeasure } from "../format";
import type { Stat } from "../mapStats";

const TOP = 10;

interface Props {
  measure: MapMeasure;
  stats: Map<string, Stat> | null;
  noun: string;
  // Itens esperados no nível (regiões ou UFs) que ficam de fora quando não têm recarga.
  expected?: { id: string; name: string }[];
  highlighted: string | null;
  interactive: boolean;
  onHighlight: (id: string | null) => void;
  onSelect: (id: string) => void;
}

export default function Ranking({
  measure,
  stats,
  noun,
  expected = [],
  highlighted,
  interactive,
  onHighlight,
  onSelect,
}: Props) {
  if (!stats) {
    return (
      <div className="skeleton-list" aria-busy="true" aria-label="Carregando o ranking">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="skeleton-row" />
        ))}
      </div>
    );
  }
  const all = [...stats.values()].sort((a, b) => a.rank - b.rank);
  // mom_change: o que interessa são as pontas, então o top 10 traz as 5 maiores altas e as 5
  // maiores quedas (a ordem segue o valor decrescente, e a posição original é mantida).
  const split = measure === "mom_change" && all.length > TOP;
  const ranked = split ? [...all.slice(0, TOP / 2), ...all.slice(-TOP / 2)] : all.slice(0, TOP);
  const missing = expected.filter((e) => !stats.has(e.id));
  return (
    <ol className="ranking" aria-label={`Ranking: ${noun}`}>
      {ranked.map((s, i) => (
        <li key={s.id} className={split && i === TOP / 2 ? "rank-gap" : undefined}>
          <button
            type="button"
            className={highlighted === s.id ? "active" : ""}
            aria-label={`${s.rank}º ${s.name}: ${formatMeasure(measure, s.value)}`}
            onClick={interactive ? () => onSelect(s.id) : undefined}
            onMouseEnter={() => onHighlight(s.id)}
            onMouseLeave={() => onHighlight(null)}
            onFocus={() => onHighlight(s.id)}
            onBlur={() => onHighlight(null)}
          >
            <span className="rank-name">
              {s.rank}º {s.name}
            </span>
            <span className="rank-value">{formatMeasure(measure, s.value)}</span>
          </button>
        </li>
      ))}
      {missing.map((e) => (
        <li key={e.id} className="rank-empty">
          {e.name}: sem recargas
        </li>
      ))}
    </ol>
  );
}
