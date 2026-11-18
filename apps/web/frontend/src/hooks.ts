import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchKpis,
  fetchMonths,
  fetchRegionMap,
  fetchUfTopology,
  type KpisResponse,
  type MapMeasure,
  type RegionValue,
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
        setResult({ id: cacheKey, data });
        setFailure(null);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setFailure({ id: cacheKey, code: errorCode(e) });
      });
    return () => ctrl.abort();
  }, [cacheKey, attempt]);

  return {
    data: result !== null && result.id === cacheKey ? result.data : null,
    stale: result?.data ?? null,
    error: failure !== null && failure.id === cacheKey ? failure.code : null,
    retry: useCallback(() => setAttempt((n) => n + 1), []),
  };
}

export function useMonths() {
  const api = useApi<string[]>("months", fetchMonths);
  return { months: api.data ?? [], error: api.error, retry: api.retry };
}

export function useKpis(month: string | null) {
  const api = useApi<KpisResponse>(month, (s) => fetchKpis(month as string, s));
  return { kpis: api.data, error: api.error, retry: api.retry };
}

export interface RegionMapData {
  month: string;
  measure: MapMeasure;
  items: RegionValue[];
}

// O resultado carrega o mês e a medida a que pertence, para que o mapa anterior mantido em erro
// continue com a legenda e a unidade certas.
export function useRegionMap(month: string | null, measure: MapMeasure) {
  const cacheKey = month === null ? null : `${month}|${measure}`;
  const api = useApi<RegionMapData>(cacheKey, async (s) => ({
    month: month as string,
    measure,
    items: await fetchRegionMap(month as string, measure, s),
  }));
  return { data: api.data, stale: api.stale, error: api.error, retry: api.retry };
}

export function useUfTopology() {
  const api = useApi<unknown>("br-uf", fetchUfTopology);
  return { topology: api.data, error: api.error, retry: api.retry };
}
