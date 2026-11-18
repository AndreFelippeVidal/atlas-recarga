import type { MapMeasure, Region } from "../api";
import { formatMeasure } from "../format";
import { REGION_NAMES } from "../regions";
import type { RegionStat } from "./RegionMap";

interface Props {
  measure: MapMeasure;
  stats: Map<Region, RegionStat> | null;
  highlighted: Region | null;
  onHighlight: (region: Region | null) => void;
}

const ALL: Region[] = ["N", "NE", "CO", "SE", "S"];

export default function Ranking({ measure, stats, highlighted, onHighlight }: Props) {
  if (!stats) {
    return (
      <p className="placeholder" aria-busy="true">
        Carregando o ranking…
      </p>
    );
  }
  const ranked = [...stats.values()].sort((a, b) => a.rank - b.rank);
  const missing = ALL.filter((r) => !stats.has(r));
  return (
    <ol className="ranking" aria-label="Ranking das regiões">
      {ranked.map((s) => (
        <li key={s.region}>
          <button
            type="button"
            className={highlighted === s.region ? "active" : ""}
            aria-label={`${s.rank}º ${REGION_NAMES[s.region]}: ${formatMeasure(measure, s.value)}`}
            onMouseEnter={() => onHighlight(s.region)}
            onMouseLeave={() => onHighlight(null)}
            onFocus={() => onHighlight(s.region)}
            onBlur={() => onHighlight(null)}
          >
            <span className="rank-name">
              {s.rank}º {REGION_NAMES[s.region]}
            </span>
            <span className="rank-value">{formatMeasure(measure, s.value)}</span>
          </button>
        </li>
      ))}
      {missing.map((r) => (
        <li key={r} className="rank-empty">
          {REGION_NAMES[r]}: sem recargas
        </li>
      ))}
    </ol>
  );
}
