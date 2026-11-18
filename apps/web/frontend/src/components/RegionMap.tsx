import { geoMercator, geoPath } from "d3-geo";
import { useMemo, useState } from "react";
import { feature, mesh } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import type { MapMeasure, Region } from "../api";
import type { RegionStat } from "../mapStats";
import { formatMeasure } from "../format";
import { REGION_NAMES } from "../regions";
import { classOf, quantileThresholds } from "../scale";

const WIDTH = 600;

function regionOf(g: { properties?: object | null }): string | undefined {
  return (g.properties as Partial<UfProps> | null | undefined)?.region;
}
const HEIGHT = 640;

interface UfProps {
  uf: string;
  region: Region;
}

interface Props {
  topology: unknown;
  measure: MapMeasure;
  // null = carregando (skeleton). Região fora do mapa = "sem recargas".
  stats: Map<Region, RegionStat> | null;
  total: number;
  highlighted: Region | null;
  onHighlight: (region: Region | null) => void;
}

interface TooltipState {
  region: Region;
  x: number;
  y: number;
}

export default function RegionMap({
  topology,
  measure,
  stats,
  total,
  highlighted,
  onHighlight,
}: Props) {
  const [tip, setTip] = useState<TooltipState | null>(null);

  const geo = useMemo(() => {
    const topo = topology as Topology;
    const obj = topo.objects.uf as GeometryCollection<UfProps>;
    const collection = feature(topo, obj);
    const projection = geoMercator().fitSize([WIDTH, HEIGHT], collection);
    const path = geoPath(projection);
    return {
      ufs: collection.features.map((f) => ({
        uf: f.properties.uf,
        region: f.properties.region,
        d: path(f) ?? "",
      })),
      regionBorders: path(mesh(topo, obj, (a, b) => regionOf(a) !== regionOf(b))) ?? "",
      outline: path(mesh(topo, obj, (a, b) => a === b)) ?? "",
    };
  }, [topology]);

  const thresholds = useMemo(
    () => (stats ? quantileThresholds([...stats.values()].map((s) => Number(s.value))) : []),
    [stats],
  );

  const fillFor = (region: Region): string => {
    if (!stats) return "var(--map-loading)";
    const stat = stats.get(region);
    if (!stat) return "url(#no-data)";
    return `var(--seq-${classOf(Number(stat.value), thresholds) + 1})`;
  };

  const labelFor = (uf: string, region: Region): string => {
    const stat = stats?.get(region);
    const value = stat ? formatMeasure(measure, stat.value) : "sem recargas";
    return `${uf}, região ${REGION_NAMES[region]}: ${value}`;
  };

  const tipStat = tip ? stats?.get(tip.region) : undefined;

  return (
    <div className="map-wrap" aria-busy={stats === null}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="group" aria-label="Mapa do Brasil por região">
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
        {geo.ufs.map((u) => (
          <path
            key={u.uf}
            d={u.d}
            role="button"
            aria-label={labelFor(u.uf, u.region)}
            className={`uf${highlighted === u.region ? " active" : ""}`}
            style={{ fill: fillFor(u.region) }}
            onMouseMove={(e) => {
              const box = e.currentTarget.ownerSVGElement?.getBoundingClientRect();
              setTip({
                region: u.region,
                x: e.clientX - (box?.left ?? 0),
                y: e.clientY - (box?.top ?? 0),
              });
            }}
            onMouseEnter={() => onHighlight(u.region)}
            onMouseLeave={() => {
              setTip(null);
              onHighlight(null);
            }}
          />
        ))}
        <path d={geo.regionBorders} className="region-border" />
        <path d={geo.outline} className="outline" />
      </svg>
      {tip && (
        <div className="tooltip" role="tooltip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
          <strong>{REGION_NAMES[tip.region]}</strong>
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
