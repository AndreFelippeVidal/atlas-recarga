// Formatação de exibição em pt-BR. Não calcula métrica: só apresenta o que a API devolveu.
import type { KpiMeasure } from "./api";

const int = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const compact = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

export function formatMeasure(measure: KpiMeasure, value: string): string {
  const n = Number(value);
  switch (measure) {
    case "gross_revenue":
      if (Math.abs(n) >= 1_000_000) return `R$ ${compact.format(n / 1_000_000)} mi`;
      return brl.format(n);
    case "avg_ticket":
      return brl.format(n);
    default:
      return int.format(n);
  }
}

export function formatDelta(deltaPct: string | null): string {
  if (deltaPct === null) return "sem base";
  const n = Number(deltaPct);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

export function formatMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const name = new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("pt-BR", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
  return name.replace(".", "");
}
