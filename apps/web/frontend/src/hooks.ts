import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchFilters,
  fetchKpis,
  fetchMonths,
  fetchMap,
  fetchMunTopology,
  fetchUfTopology,
  type Filters,
  type FilterOptions,
  type KpisResponse,
  type MapFocus,
  type MapItem,
  type MapMeasure,
} from "./api";

function errorCode(err: unknown): string {
  return err instanceof ApiError ? err.code : "UNKNOWN";
}

// Busca com chave. `data` é o resultado da chave atual (ou null enquanto carrega); `stale` é o
// último resultado de qualquer chave, para manter o mapa anterior em erro (SPEC-007 §4). O erro
// guarda a chave a que pertence: ao trocar a chave, o erro antigo some sozinho.
export function useApi<T>(cacheKey: string | null, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<{ id: string; data: T } | null>(null);
  const [failure, setFailure] = useState<{ id: string; code: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (cacheKey === null) return;
    const ctrl = new AbortController();
    fetcherRef
      .current(ctrl.signal)
      .then((data) => {
        if (ctrl.signal.aborted) return;
        setResult({ id: cacheKey, data });
        setFailure(null);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setFailure({ id: `${cacheKey}#${attempt}`, code: errorCode(e) });
      });
    return () => ctrl.abort();
  }, [cacheKey, attempt]);

  return {
    data: result !== null && result.id === cacheKey ? result.data : null,
    stale: result?.data ?? null,
    // O erro vale só para a chave e a tentativa atuais: ao tentar de novo, o banner some.
    error: failure !== null && failure.id === `${cacheKey}#${attempt}` ? failure.code : null,
    retry: useCallback(() => setAttempt((n) => n + 1), []),
  };
}

export function useMonths() {
  const api = useApi<string[]>("months", fetchMonths);
  return {
    months: api.data ?? [],
    // Ainda sem resposta nem erro: a lista de meses está a caminho.
    loading: api.data === null && api.error === null,
    error: api.error,
    retry: api.retry,
  };
}

export function filtersKey(f: Filters): string {
  return JSON.stringify([f.pos_type ?? "", f.distributor ?? ""]);
}

export function useFilterOptions() {
  const api = useApi<FilterOptions>("filters", fetchFilters);
  return { options: api.data, error: api.error, retry: api.retry };
}

export function useKpis(month: string | null, filters: Filters = {}) {
  const api = useApi<KpisResponse>(month === null ? null : `${month}|${filtersKey(filters)}`, (s) =>
    fetchKpis(month as string, filters, s),
  );
  return { kpis: api.data, error: api.error, retry: api.retry };
}

export interface MapData {
  month: string;
  filtersKey: string;
  measure: MapMeasure;
  focus: MapFocus;
  items: MapItem[];
}

function focusKey(focus: MapFocus): string {
  if (focus.level === "brazil") return "brazil";
  return focus.level === "region" ? `region:${focus.region}` : `uf:${focus.uf}`;
}

// O resultado carrega mês, medida e foco a que pertence, para que o mapa anterior mantido em erro
// continue com a legenda, a unidade e a geometria certas.
export function useMapData(
  month: string | null,
  measure: MapMeasure,
  focus: MapFocus,
  filters: Filters = {},
) {
  const cacheKey =
    month === null ? null : `${month}|${measure}|${focusKey(focus)}|${filtersKey(filters)}`;
  const api = useApi<MapData>(cacheKey, async (s) => ({
    month: month as string,
    filtersKey: filtersKey(filters),
    measure,
    focus,
    items: await fetchMap(month as string, measure, focus, filters, s),
  }));
  return { data: api.data, stale: api.stale, error: api.error, retry: api.retry };
}

export function useUfTopology() {
  const api = useApi<unknown>("br-uf", fetchUfTopology);
  return { topology: api.data, error: api.error, retry: api.retry };
}

// Malha dos municípios da UF, carregada sob demanda. Guarda a UF a que pertence.
export function useMunTopology(uf: string | null) {
  const api = useApi<{ uf: string; topology: unknown }>(
    uf === null ? null : `mun:${uf}`,
    async (s) => ({
      uf: uf as string,
      topology: await fetchMunTopology(uf as string, s),
    }),
  );
  return {
    topology: uf !== null ? (api.data?.topology ?? null) : null,
    error: api.error,
    retry: api.retry,
  };
}

export const WARMUP_MS = 3000;

// Verdadeiro quando a espera passa de `ms` (warehouse frio, SPEC-007 §4). Volta a falso assim que
// a espera termina ou recomeça do zero ao trocar de consulta.
export function useSlow(pending: boolean, ms = WARMUP_MS): boolean {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => setSlow(true), ms);
    return () => {
      clearTimeout(timer);
      setSlow(false);
    };
  }, [pending, ms]);
  return pending && slow;
}
