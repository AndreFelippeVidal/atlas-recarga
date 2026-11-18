import type { MapMeasure } from "../api";
import { formatCompact, MEASURE_UNITS } from "../format";
import { classColor, type LegendClass, type Scale } from "../scale";

interface Props {
  measure: MapMeasure;
  scale: Scale;
  classes: LegendClass[];
  hasEmpty: boolean;
}

function title(measure: MapMeasure, scale: Scale): string {
  if (scale.kind === "sequential") return `Classes por quantis (${MEASURE_UNITS[measure]})`;
  const bound = scale.bound ? ` ±${formatCompact(measure, scale.bound).replace("+", "")}` : "";
  return `Escala divergente centrada em 0%${bound} (${MEASURE_UNITS[measure]})`;
}

const DIRECTION = ["maior queda", "queda", "estável", "alta", "maior alta"];

export default function Legend({ measure, scale, classes, hasEmpty }: Props) {
  return (
    <div className="legend" role="group" aria-label={`Legenda, em ${MEASURE_UNITS[measure]}`}>
      <div className="legend-title">{title(measure, scale)}</div>
      <ul>
        {classes.map((c) => (
          <li key={c.index}>
            <span className="swatch" style={{ background: classColor(scale, c.index) }} />
            {c.from === c.to
              ? formatCompact(measure, c.from)
              : `${formatCompact(measure, c.from)} a ${formatCompact(measure, c.to)}`}
            {scale.kind === "diverging" && <span className="muted"> ({DIRECTION[c.index]})</span>}
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
