import { buildStats } from "./mapStats";
import {
  buildScale,
  classColor,
  classOf,
  divergingBound,
  divergingThresholds,
  legendClasses,
  quantileThresholds,
  scaleClass,
} from "./scale";

describe("quantis", () => {
  it("com 5 valores cada um cai numa classe própria", () => {
    const values = [10, 20, 30, 40, 50];
    const t = quantileThresholds(values);
    expect(t).toHaveLength(4);
    expect(values.map((v) => classOf(v, t))).toEqual([0, 1, 2, 3, 4]);
  });

  it("valores iguais ficam na mesma classe", () => {
    const t = quantileThresholds([5, 5, 5, 5, 5]);
    expect(new Set([5, 5].map((v) => classOf(v, t))).size).toBe(1);
  });

  it("não quebra sem valores", () => {
    expect(quantileThresholds([])).toEqual([]);
    expect(legendClasses([], buildScale("gross_revenue", []))).toEqual([]);
  });

  it("a legenda traz a faixa observada de cada classe e omite as vazias", () => {
    const values = [10, 20, 30];
    const classes = legendClasses(values, buildScale("gross_revenue", values));
    expect(classes.map((c) => [c.from, c.to])).toEqual([
      [10, 10],
      [20, 20],
      [30, 30],
    ]);
  });
});

describe("ranking", () => {
  it("ordena por valor decrescente e numera a posição", () => {
    const stats = buildStats([
      { id: "N", name: "Norte", value: "300000.00" },
      { id: "SE", name: "Sudeste", value: "2500000.00" },
      { id: "S", name: "Sul", value: "900000.50" },
    ]);
    expect([...stats.values()].map((s) => [s.id, s.rank])).toEqual([
      ["SE", 1],
      ["S", 2],
      ["N", 3],
    ]);
  });

  it("deixa de fora as linhas sem valor (mom_change sem base)", () => {
    const stats = buildStats([
      { id: "N", name: "Norte", value: null },
      { id: "S", name: "Sul", value: "-3.50" },
    ]);
    expect([...stats.keys()]).toEqual(["S"]);
  });
});

describe("escala divergente (mom_change)", () => {
  it("é simétrica em ±max(|min|, |max|) e centrada em 0", () => {
    const values = [-40, -10, 0, 4, 20];
    const t = divergingThresholds(values);
    expect(t).toEqual([-24, -8, 8, 24]);
    expect(divergingBound(values)).toBe(40);
  });

  it("a maior queda cai na classe 0 e a maior alta na 4, mesmo com alta pequena", () => {
    const scale = buildScale("mom_change", [-40, 4]);
    expect(scaleClass(scale, -40)).toBe(0);
    expect(scaleClass(scale, 4)).toBe(2);
    expect(scaleClass(buildScale("mom_change", [-10, 40]), 40)).toBe(4);
  });

  it("o zero fica na classe do meio e tudo zero não quebra", () => {
    const scale = buildScale("mom_change", [-30, 30]);
    expect(scaleClass(scale, 0)).toBe(2);
    const flat = buildScale("mom_change", [0, 0]);
    expect(scaleClass(flat, 0)).toBe(2);
    expect(buildScale("mom_change", []).thresholds).toEqual([0, 0, 0, 0]);
    expect(legendClasses([0, 0], flat).map((c) => c.index)).toEqual([2]);
  });

  it("volume segue os quantis e as cores vêm de --seq / --div", () => {
    const seq = buildScale("gross_revenue", [10, 20, 30, 40, 50]);
    expect(seq.kind).toBe("sequential");
    expect(classColor(seq, 0)).toBe("var(--seq-1)");
    expect(classColor(buildScale("mom_change", [1]), 4)).toBe("var(--div-5)");
  });
});
