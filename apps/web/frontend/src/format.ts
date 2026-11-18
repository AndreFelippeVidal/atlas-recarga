// Formatação de exibição em pt-BR. Não calcula métrica: só apresenta o que a API devolveu.
import type { KpiMeasure } from "./api";

const int = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export function formatMeasure(measure: KpiMeasure, value: string): string {
  const n = Number(value);
  switch (measure) {
    case "gross_revenue":
    case "avg_ticket":
      // Intl aceita a string decimal: o valor DECIMAL(14,2) sai exato, sem passar por float.
      return brl.format(value as unknown as number);
    default:
      return int.format(n);
  }
}

// Arredonda como o texto exibido, para que sinal, seta e cor nunca contradigam o número.
export function roundedDelta(deltaPct: string): number {
  return Number(Number(deltaPct).toFixed(2)) + 0;
}

export function formatDelta(deltaPct: string | null): string {
  if (deltaPct === null) return "sem base";
  const n = roundedDelta(deltaPct);
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
