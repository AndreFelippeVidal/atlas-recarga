import type { MapMeasure } from "../api";
import { formatCompact, MEASURE_UNITS } from "../format";
import type { LegendClass } from "../scale";

interface Props {
  measure: MapMeasure;
  classes: LegendClass[];
  hasEmpty: boolean;
}

export default function Legend({ measure, classes, hasEmpty }: Props) {
  return (
    <div className="legend" aria-label={`Legenda, em ${MEASURE_UNITS[measure]}`}>
      <div className="legend-title">Classes por quantis ({MEASURE_UNITS[measure]})</div>
      <ul>
        {classes.map((c) => (
          <li key={c.index}>
            <span className="swatch" style={{ background: `var(--seq-${c.index + 1})` }} />
            {c.from === c.to
              ? formatCompact(measure, c.from)
              : `${formatCompact(measure, c.from)} a ${formatCompact(measure, c.to)}`}
          </li>
        ))}
        {hasEmpty && (
          <li>
            <span className="swatch hatched" />
            sem recargas
          </li>
        )}
      </ul>
    </div>
  );
}
