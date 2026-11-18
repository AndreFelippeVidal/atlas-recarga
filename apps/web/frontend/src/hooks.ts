import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchKpis, fetchMonths, type KpisResponse } from "./api";

function errorCode(err: unknown): string {
  return err instanceof ApiError ? err.code : "UNKNOWN";
}

// Mantém o dado anterior em erro (SPEC-007 §4: o banner não apaga o que já estava na tela).
export function useMonths() {
  const [months, setMonths] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchMonths(ctrl.signal)
      .then((m) => {
        setMonths(m);
        setError(null);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(errorCode(e));
      });
    return () => ctrl.abort();
  }, [attempt]);

  return { months, error, retry: useCallback(() => setAttempt((n) => n + 1), []) };
}

export function useKpis(month: string | null) {
  const [kpis, setKpis] = useState<KpisResponse | null>(null);
  // O erro guarda o mês a que pertence: ao trocar de mês, o erro antigo some sozinho.
  const [failure, setFailure] = useState<{ month: string; code: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!month) return;
    const ctrl = new AbortController();
    fetchKpis(month, ctrl.signal)
      .then((k) => {
        setKpis(k);
        setFailure(null);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setFailure({ month, code: errorCode(e) });
      });
    return () => ctrl.abort();
  }, [month, attempt]);

  // Só mostra o KPI se for do mês pedido; senão, skeleton.
  const current = kpis && kpis.month === month ? kpis : null;
  const error = failure && failure.month === month ? failure.code : null;
  return { kpis: current, error, retry: useCallback(() => setAttempt((n) => n + 1), []) };
}
