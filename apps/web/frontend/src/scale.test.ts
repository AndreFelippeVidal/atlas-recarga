import { buildStats } from "./mapStats";
import { classOf, legendClasses, quantileThresholds } from "./scale";

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
    expect(legendClasses([], [])).toEqual([]);
  });

  it("a legenda traz a faixa observada de cada classe e omite as vazias", () => {
    const values = [10, 20, 30];
    const classes = legendClasses(values, quantileThresholds(values));
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
