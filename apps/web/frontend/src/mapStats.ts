import type { MapItem } from "./api";

export interface Stat {
  id: string;
  name: string;
  value: string;
  rank: number;
}

// Posição no ranking por valor decrescente. Ordena para exibir; não calcula nenhuma métrica.
// Linhas sem valor (mom_change sem base) ficam de fora: são tratadas como "sem recargas".
export function buildStats(items: MapItem[]): Map<string, Stat> {
  const withValue = items.filter((i): i is MapItem & { value: string } => i.value !== null);
  const sorted = [...withValue].sort((a, b) => Number(b.value) - Number(a.value));
  return new Map(
    sorted.map((item, i) => [
      item.id,
      { id: item.id, name: item.name, value: item.value, rank: i + 1 },
    ]),
  );
}
