import { useMemo, useState } from "react";
import type { MapMeasure, Region } from "../api";
import { useRegionMap, useUfTopology } from "../hooks";
import { buildStats } from "../mapStats";
import { REGIONS } from "../regions";
import { legendClasses, quantileThresholds } from "../scale";
import ErrorBanner from "./ErrorBanner";
import Legend from "./Legend";
import Ranking from "./Ranking";
import RegionMap from "./RegionMap";

interface Props {
  month: string | null;
  measure: MapMeasure;
}

export default function MapPanel({ month, measure }: Props) {
  const geo = useUfTopology();
  const regionMap = useRegionMap(month, measure);
  const [highlighted, setHighlighted] = useState<Region | null>(null);

  // Em erro mantém o mapa anterior (com a medida a que ele pertence); carregando, mostra skeleton.
  const shown = regionMap.data ?? (regionMap.error ? regionMap.stale : null);
  const stats = useMemo(() => (shown ? buildStats(shown.items) : null), [shown]);
  const classes = useMemo(() => {
    if (!stats) return [];
    const values = [...stats.values()].map((s) => Number(s.value));
    return legendClasses(values, quantileThresholds(values));
  }, [stats]);

  const error = geo.error ?? regionMap.error;
  const retry = () => {
    if (geo.error) geo.retry();
    if (regionMap.error) regionMap.retry();
  };
  const shownMeasure = shown?.measure ?? measure;

  return (
    <>
      <section className="map-area" aria-label="Mapa">
        {error && <ErrorBanner code={error} onRetry={retry} />}
        {geo.topology ? (
          <RegionMap
            topology={geo.topology}
            measure={shownMeasure}
            stats={stats}
            total={REGIONS.length}
            highlighted={highlighted}
            onHighlight={setHighlighted}
          />
        ) : (
          <p className="placeholder" aria-busy="true">
            Carregando o mapa…
          </p>
        )}
        {stats && (
          <Legend measure={shownMeasure} classes={classes} hasEmpty={stats.size < REGIONS.length} />
        )}
      </section>
      <aside className="side" aria-label="Ranking">
        <nav aria-label="Navegação do mapa" className="breadcrumb">
          Brasil
        </nav>
        <Ranking
          measure={shownMeasure}
          stats={stats}
          highlighted={highlighted}
          onHighlight={setHighlighted}
        />
      </aside>
    </>
  );
}
