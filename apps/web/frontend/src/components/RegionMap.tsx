import { useMemo, useState } from "react";
import type { MapMeasure } from "../api";
import { formatMeasure } from "../format";
import type { Geometry } from "../geoShapes";
import { HEIGHT, WIDTH } from "../geoShapes";
import type { Stat } from "../mapStats";
import { buildScale, classColor, scaleClass } from "../scale";

interface Props {
  geometry: Geometry;
  measure: MapMeasure;
  // null = carregando (skeleton). Chave fora do mapa = "sem recargas".
  stats: Map<string, Stat> | null;
  label: string;
  // Só os níveis Brasil e região têm um nível abaixo para onde descer.
  interactive: boolean;
  highlighted: string | null;
  onHighlight: (statKey: string | null) => void;
  onSelect: (statKey: string) => void;
}

interface TooltipState {
  statKey: string;
  title: string;
  x: number;
  y: number;
}

export default function RegionMap({
  geometry,
  measure,
  stats,
  label,
  interactive,
  highlighted,
  onHighlight,
  onSelect,
}: Props) {
  const [tip, setTip] = useState<TooltipState | null>(null);

  const scale = useMemo(
    () => buildScale(measure, stats ? [...stats.values()].map((s) => Number(s.value)) : []),
    [measure, stats],
  );
  const total = useMemo(() => new Set(geometry.shapes.map((s) => s.statKey)).size, [geometry]);

  const fillFor = (statKey: string): string => {
    if (!stats) return "var(--map-loading)";
    const stat = stats.get(statKey);
    if (!stat) return "url(#no-data)";
    return classColor(scale, scaleClass(scale, Number(stat.value)));
  };

  const labelFor = (ariaName: string, statKey: string): string => {
    const stat = stats?.get(statKey);
    return `${ariaName}: ${stat ? formatMeasure(measure, stat.value) : "sem recargas"}`;
  };

  const tipStat = tip ? stats?.get(tip.statKey) : undefined;
  const tipTitle = tip ? (tipStat?.name ?? tip.title) : "";

  return (
    <div className={`map-wrap${stats === null ? " loading" : ""}`} aria-busy={stats === null}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="group" aria-label={label}>
        <defs>
          <pattern
            id="no-data"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="6" height="6" fill="var(--map-empty)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--map-hatch)" strokeWidth="2" />
          </pattern>
        </defs>
        <g className="shapes">
          {geometry.shapes.map((s) => (
            <path
              key={s.id}
              d={s.d}
              role={interactive ? "button" : "img"}
              tabIndex={interactive ? 0 : undefined}
              aria-label={labelFor(s.ariaName, s.statKey)}
              className={`uf${highlighted === s.statKey ? " active" : ""}${interactive ? " clickable" : ""}`}
              style={{ fill: fillFor(s.statKey) }}
              onClick={interactive ? () => onSelect(s.statKey) : undefined}
              onKeyDown={
                interactive
                  ? (ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        onSelect(s.statKey);
                      }
                    }
                  : undefined
              }
              onMouseMove={(ev) => {
                const box = ev.currentTarget.ownerSVGElement?.getBoundingClientRect();
                setTip({
                  statKey: s.statKey,
                  title: s.title,
                  x: ev.clientX - (box?.left ?? 0),
                  y: ev.clientY - (box?.top ?? 0),
                });
              }}
              onMouseEnter={() => onHighlight(s.statKey)}
              onFocus={interactive ? () => onHighlight(s.statKey) : undefined}
              onBlur={interactive ? () => onHighlight(null) : undefined}
              onMouseLeave={() => {
                setTip(null);
                onHighlight(null);
              }}
            />
          ))}
        </g>
        {geometry.regionBorders && <path d={geometry.regionBorders} className="region-border" />}
        <path d={geometry.outline} className="outline" />
      </svg>
      {tip && (
        <div className="tooltip" role="tooltip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
          <strong>{tipTitle}</strong>
          {tipStat ? (
            <>
              <div>{formatMeasure(measure, tipStat.value)}</div>
              <div className="muted">
                {tipStat.rank}º de {total}
              </div>
            </>
          ) : (
            <div className="muted">sem recargas</div>
          )}
        </div>
      )}
    </div>
  );
}
