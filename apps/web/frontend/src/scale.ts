// Escala de quantis para o coroplético (SPEC-007 §4). Só classifica valores que a API já
// devolveu: nenhuma métrica é calculada aqui.

export const CLASS_COUNT = 5;

function quantile(sorted: number[], p: number): number {
  const pos = (sorted.length - 1) * p;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// Limites entre classes (k - 1 valores crescentes), pelo mesmo método de interpolação do d3.
export function quantileThresholds(values: number[], k = CLASS_COUNT): number[] {
  if (values.length === 0) return [];
  const sorted = [...values].sort((a, b) => a - b);
  return Array.from({ length: k - 1 }, (_, i) => quantile(sorted, (i + 1) / k));
}

export function classOf(value: number, thresholds: number[]): number {
  return thresholds.filter((t) => t <= value).length;
}

export interface LegendClass {
  index: number;
  from: number;
  to: number;
}

// Faixa de valores observada em cada classe, para a legenda (classes vazias ficam de fora).
export function legendClasses(
  values: number[],
  thresholds: number[],
  k = CLASS_COUNT,
): LegendClass[] {
  const out: LegendClass[] = [];
  for (let index = 0; index < k; index++) {
    const inClass = values.filter((v) => classOf(v, thresholds) === index);
    if (inClass.length > 0) {
      out.push({ index, from: Math.min(...inClass), to: Math.max(...inClass) });
    }
  }
  return out;
}
