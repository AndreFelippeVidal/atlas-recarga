// Cliente da API do backend (SPEC-007 §3). Valores numéricos chegam como string decimal e
// ficam strings: o frontend só formata, nunca calcula métrica.

export type KpiMeasure = "gross_revenue" | "recharge_count" | "avg_ticket" | "active_pos";

export interface Kpi {
  value: string;
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

export async function fetchMonths(signal?: AbortSignal): Promise<string[]> {
  return (await getJson<{ months: string[] }>("/api/months", signal)).months;
}

export function fetchKpis(month: string, signal?: AbortSignal): Promise<KpisResponse> {
  return getJson<KpisResponse>(`/api/kpis?month=${encodeURIComponent(month)}`, signal);
}
