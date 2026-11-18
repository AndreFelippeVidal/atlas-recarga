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
export function legendClasses(values: number[], scale: Scale, k = CLASS_COUNT): LegendClass[] {
  const out: LegendClass[] = [];
  for (let index = 0; index < k; index++) {
    const inClass = values.filter((v) => scaleClass(scale, v) === index);
    if (inClass.length > 0) {
      out.push({ index, from: Math.min(...inClass), to: Math.max(...inClass) });
    }
  }
  return out;
}

// Escala divergente de `mom_change` (SPEC-007 §4): 5 classes de largura igual, centradas em 0 e
// simétricas em ±max(|min|, |max|). Só classifica valores já devolvidos pela API.
export function divergingBound(values: number[]): number {
  return values.length === 0 ? 0 : Math.max(...values.map((v) => Math.abs(v)));
}

export function divergingThresholds(values: number[], k = CLASS_COUNT): number[] {
  const bound = divergingBound(values);
  return Array.from({ length: k - 1 }, (_, i) => -bound + (2 * bound * (i + 1)) / k);
}

export interface Scale {
  kind: "sequential" | "diverging";
  thresholds: number[];
  // ±max(|min|, |max|); só na divergente (a legenda mostra a simetria).
  bound: number | null;
}

export function buildScale(measure: string, values: number[]): Scale {
  if (measure === "mom_change") {
    return {
      kind: "diverging",
      thresholds: divergingThresholds(values),
      bound: divergingBound(values),
    };
  }
  return { kind: "sequential", thresholds: quantileThresholds(values), bound: null };
}

// Classe (0 a 4) de um valor na escala. Na divergente, tudo zero cai na classe do meio.
export function scaleClass(scale: Scale, value: number): number {
  if (scale.kind === "diverging" && scale.bound === 0) return Math.floor(CLASS_COUNT / 2);
  return classOf(value, scale.thresholds);
}

// Variável CSS da cor da classe: `--seq-*` (volume) ou `--div-*` (mom_change).
export function classColor(scale: Scale, index: number): string {
  return `var(--${scale.kind === "diverging" ? "div" : "seq"}-${index + 1})`;
}
