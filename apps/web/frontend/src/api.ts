import { REGION_NAMES } from "./regions";

// Cliente da API do backend (SPEC-007 §3). Valores numéricos chegam como string decimal e
// ficam strings: o frontend só formata, nunca calcula métrica.

export type KpiMeasure = "gross_revenue" | "recharge_count" | "avg_ticket" | "active_pos";

export interface Kpi {
  // `null` só em avg_ticket de um recorte sem recarga (SPEC-007 §3).
  value: string | null;
  previous: string | null;
  delta_pct: string | null;
}

export interface KpisResponse {
  month: string;
  previous_month: string;
  gross_revenue: Kpi;
  recharge_count: Kpi;
  avg_ticket: Kpi;
  active_pos: Kpi;
}

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("NETWORK_ERROR", "API fora do ar");
  }
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = res.statusText;
    try {
      const body = (await res.json()) as { detail?: { code?: string; message?: string } };
      code = body.detail?.code ?? code;
      message = body.detail?.message ?? message;
    } catch {
      // corpo sem JSON: fica o código HTTP
    }
    throw new ApiError(code, message);
  }
  return (await res.json()) as T;
}

// Filtros opcionais (SPEC-007 §3, v1.1): ausente = "Todos".
export interface Filters {
  pos_type?: string;
  distributor?: string;
}

export interface FilterOptions {
  pos_types: string[];
  distributors: string[];
}

function filterQs(filters: Filters): string {
  let qs = "";
  if (filters.pos_type) qs += `&pos_type=${encodeURIComponent(filters.pos_type)}`;
  if (filters.distributor) qs += `&distributor=${encodeURIComponent(filters.distributor)}`;
  return qs;
}

export function fetchFilters(signal?: AbortSignal): Promise<FilterOptions> {
  return getJson<FilterOptions>("/api/filters", signal);
}

export async function fetchMonths(signal?: AbortSignal): Promise<string[]> {
  return (await getJson<{ months: string[] }>("/api/months", signal)).months;
}

export function fetchKpis(
  month: string,
  filters: Filters = {},
  signal?: AbortSignal,
): Promise<KpisResponse> {
  return getJson<KpisResponse>(
    `/api/kpis?month=${encodeURIComponent(month)}${filterQs(filters)}`,
    signal,
  );
}

export type Region = "N" | "NE" | "CO" | "SE" | "S";
export type MapMeasure = KpiMeasure | "mom_change";

// Nível do mapa em foco (SPEC-007 §4): Brasil (regiões), uma região (UFs) ou uma UF (municípios).
export type MapFocus =
  | { level: "brazil" }
  | { level: "region"; region: Region }
  | { level: "uf"; uf: string; region: Region };

// Linha normalizada dos três endpoints `/api/map/*`. `value` nulo = sem base (mom_change).
export interface MapItem {
  id: string;
  name: string;
  value: string | null;
}

interface RawRow {
  region?: string;
  uf?: string;
  municipality_ibge_code?: string;
  municipality_name?: string | null;
  value: string | null;
}

export async function fetchMap(
  month: string,
  measure: MapMeasure,
  focus: MapFocus,
  filters: Filters = {},
  signal?: AbortSignal,
): Promise<MapItem[]> {
  let qs = `month=${encodeURIComponent(month)}&measure=${encodeURIComponent(measure)}${filterQs(filters)}`;
  let path = "/api/map/region";
  if (focus.level === "region") {
    path = "/api/map/uf";
    qs += `&region=${focus.region}`;
  } else if (focus.level === "uf") {
    path = "/api/map/municipality";
    qs += `&uf=${focus.uf}`;
  }
  const rows = await getJson<RawRow[]>(`${path}?${qs}`, signal);
  return rows.map((r) => {
    const id = r.municipality_ibge_code ?? r.uf ?? r.region ?? "";
    const name = r.municipality_name ?? REGION_NAMES[id as Region] ?? id;
    return { id, name, value: r.value };
  });
}

export function fetchUfTopology(signal?: AbortSignal): Promise<unknown> {
  return getJson<unknown>("/geo/br-uf.json", signal);
}

export function fetchMunTopology(uf: string, signal?: AbortSignal): Promise<unknown> {
  return getJson<unknown>(`/geo/mun/${encodeURIComponent(uf)}.json`, signal);
}
