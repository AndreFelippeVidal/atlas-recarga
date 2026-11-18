import type { Region, RegionValue } from "./api";
import type { RegionStat } from "./components/RegionMap";

// Posição no ranking por valor decrescente. Ordena para exibir; não calcula nenhuma métrica.
export function buildStats(items: RegionValue[]): Map<Region, RegionStat> {
  const sorted = [...items].sort((a, b) => Number(b.value) - Number(a.value));
  return new Map(
    sorted.map((item, i) => [item.region, { region: item.region, value: item.value, rank: i + 1 }]),
  );
}
