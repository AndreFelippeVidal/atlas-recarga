import { useEffect, useMemo, useState } from "react";
import type { Filters, MapFocus, MapMeasure, Region } from "../api";
import { buildGeometry } from "../geoShapes";
import { useMapData, useMunTopology, useSlow, useUfTopology } from "../hooks";
import { buildStats } from "../mapStats";
import { REGION_NAMES, REGIONS } from "../regions";
import { buildScale, legendClasses } from "../scale";
import ErrorBanner from "./ErrorBanner";
import Legend from "./Legend";
import Ranking from "./Ranking";
import RegionMap from "./RegionMap";

interface Props {
  month: string | null;
  measure: MapMeasure;
  // Os meses ainda podem estar chegando (sem erro): conta como espera do warehouse.
  monthLoading: boolean;
  filters: Filters;
  onClearFilters: () => void;
}

const BRAZIL: MapFocus = { level: "brazil" };

// Sobe um nível: município → região da UF → Brasil.
function parentOf(focus: MapFocus): MapFocus {
  if (focus.level === "uf") return { level: "region", region: focus.region };
  return BRAZIL;
}

const NOUNS = { brazil: "regiões", region: "UFs da região", uf: "municípios da UF" } as const;
const MAP_LABELS = {
  brazil: "Mapa do Brasil por região",
  region: "Mapa da região por UF",
  uf: "Mapa da UF por município",
} as const;

function focusId(focus: MapFocus): string {
  if (focus.level === "uf") return `uf:${focus.uf}`;
  return focus.level === "region" ? `region:${focus.region}` : "brazil";
}

export default function MapPanel({ month, measure, monthLoading, filters, onClearFilters }: Props) {
  const [focus, setFocus] = useState<MapFocus>(BRAZIL);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const geo = useUfTopology();
  const mapData = useMapData(month, measure, focus, filters);

  // Em erro mantém o mapa anterior (com mês, medida e foco a que ele pertence); carregando,
  // mostra o esqueleto do foco pedido.
  const shown = mapData.data ?? (mapData.error ? mapData.stale : null);
  const view = shown?.focus ?? focus;
  const mun = useMunTopology(view.level === "uf" ? view.uf : null);

  const geometry = useMemo(
    () => buildGeometry(geo.topology, mun.topology, view),
    [geo.topology, mun.topology, view],
  );
  const stats = useMemo(() => (shown ? buildStats(shown.items) : null), [shown]);
  const scale = useMemo(
    () =>
      buildScale(
        shown?.measure ?? measure,
        stats ? [...stats.values()].map((s) => Number(s.value)) : [],
      ),
    [shown, measure, stats],
  );
  const classes = useMemo(
    () =>
      stats
        ? legendClasses(
            [...stats.values()].map((s) => Number(s.value)),
            scale,
          )
        : [],
    [stats, scale],
  );
  const expected = useMemo(() => {
    if (view.level === "brazil") return REGIONS.map((r) => ({ id: r, name: REGION_NAMES[r] }));
    if (view.level === "region" && geometry) {
      return geometry.shapes.map((s) => ({ id: s.statKey, name: s.title }));
    }
    return [];
  }, [view, geometry]);

  // Esc sobe um nível a partir do que está na tela (SPEC-007 §4).
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && view.level !== "brazil") {
        setHighlighted(null);
        setFocus(parentOf(view));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view]);

  const goTo = (next: MapFocus) => {
    setHighlighted(null);
    setFocus(next);
  };
  const select = (id: string) => {
    if (view.level === "brazil") goTo({ level: "region", region: id as Region });
    else if (view.level === "region") goTo({ level: "uf", uf: id, region: view.region });
  };

  const error = geo.error ?? mapData.error ?? mun.error;
  const retry = () => {
    if (geo.error) geo.retry();
    if (mapData.error) mapData.retry();
    if (mun.error) mun.retry();
  };
  const shownMeasure = shown?.measure ?? measure;
  const totalItems =
    expected.length > 0 ? expected.length : new Set(geometry?.shapes.map((x) => x.statKey)).size;
  const mapPending = month === null ? monthLoading : mapData.data === null && !mapData.error;
  const warming = useSlow(mapPending);
  // Recorte filtrado sem nenhuma recarga no nível atual: o nível e o zoom ficam, só o vazio aparece.
  const filtered = Boolean(filters.pos_type || filters.distributor);
  const emptySlice = filtered && mapData.data !== null && mapData.data.items.length === 0;
  const hasEmpty = geometry !== null && stats !== null && stats.size < totalItems;

  return (
    <>
      <section className="map-area" aria-label="Mapa">
        {error && <ErrorBanner code={error} onRetry={retry} />}
        <div className="sr-only" role="status">
          {`${MAP_LABELS[view.level]}${mapPending || !geometry ? ": carregando" : ""}`}
        </div>
        {warming && (
          <div className="warming" role="status">
            Aquecendo o banco de dados…
          </div>
        )}
        {view.level !== "brazil" && (
          <button type="button" className="back-button" onClick={() => goTo(BRAZIL)}>
            ← Ver o Brasil inteiro
          </button>
        )}
        {emptySlice ? (
          <div className="empty-slice" role="status">
            <p>Sem recargas neste recorte</p>
            {view.level !== "brazil" && (
              <p>Neste nível do mapa; os KPIs mostram o total do recorte.</p>
            )}
            <button type="button" className="back-button" onClick={onClearFilters}>
              Limpar filtros
            </button>
          </div>
        ) : geometry ? (
          <div key={focusId(view)} className="map-zoom">
            <RegionMap
              geometry={geometry}
              measure={shownMeasure}
              stats={stats}
              label={MAP_LABELS[view.level]}
              interactive={view.level !== "uf"}
              highlighted={highlighted}
              onHighlight={setHighlighted}
              onSelect={select}
            />
          </div>
        ) : (
          <div className="skeleton-map" aria-busy="true" aria-label="Carregando o mapa" />
        )}
        {stats && geometry && !emptySlice && (
          <Legend measure={shownMeasure} scale={scale} classes={classes} hasEmpty={hasEmpty} />
        )}
      </section>
      <aside className="side" aria-label="Ranking">
        <nav aria-label="Navegação do mapa" className="breadcrumb">
          {view.level === "brazil" ? (
            <span aria-current="page">Brasil</span>
          ) : (
            <button type="button" className="crumb" onClick={() => goTo(BRAZIL)}>
              Brasil
            </button>
          )}
          {view.level !== "brazil" && (
            <>
              {" › "}
              {view.level === "region" ? (
                <span aria-current="page">{REGION_NAMES[view.region]}</span>
              ) : (
                <button
                  type="button"
                  className="crumb"
                  onClick={() => goTo({ level: "region", region: view.region })}
                >
                  {REGION_NAMES[view.region]}
                </button>
              )}
            </>
          )}
          {view.level === "uf" && (
            <>
              {" › "}
              <span aria-current="page">{view.uf}</span>
            </>
          )}
        </nav>
        {!emptySlice && (
          <Ranking
            measure={shownMeasure}
            stats={stats}
            noun={NOUNS[view.level]}
            expected={expected}
            highlighted={highlighted}
            interactive={view.level !== "uf"}
            onHighlight={setHighlighted}
            onSelect={select}
          />
        )}
      </aside>
    </>
  );
}
