// Formatação de exibição em pt-BR. Não calcula métrica: só apresenta o que a API devolveu.
import type { MapMeasure } from "./api";

const int = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export function formatMeasure(measure: MapMeasure, value: string): string {
  const n = Number(value);
  switch (measure) {
    case "mom_change":
      return formatDelta(value);
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

const compactNum = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const ticket = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// Forma curta para legenda e tooltip (`R$ 1,2 mi`, `12.345`). Só exibição.
export function formatCompact(measure: MapMeasure, n: number): string {
  if (measure === "mom_change") return formatDelta(String(n));
  const money = measure === "gross_revenue" || measure === "avg_ticket";
  const abs = Math.abs(n);
  let scaled: string;
  if (abs >= 1_000_000_000) scaled = `${compactNum.format(n / 1_000_000_000)} bi`;
  else if (abs >= 999_950) scaled = `${compactNum.format(n / 1_000_000)} mi`;
  else if (abs >= 10_000) scaled = `${compactNum.format(n / 1_000)} mil`;
  else scaled = measure === "avg_ticket" ? ticket.format(n) : int.format(n);
  return money ? `R$ ${scaled}` : scaled;
}

export const MEASURE_UNITS: Record<MapMeasure, string> = {
  gross_revenue: "R$",
  recharge_count: "recargas",
  avg_ticket: "R$ por recarga",
  active_pos: "PDVs",
  mom_change: "Δ% da receita contra o mês anterior",
};

export const MEASURE_LABELS: Record<MapMeasure, string> = {
  gross_revenue: "Receita bruta",
  recharge_count: "Recargas",
  avg_ticket: "Ticket médio",
  active_pos: "PDVs ativos",
  mom_change: "Variação da receita (Δ%)",
};
