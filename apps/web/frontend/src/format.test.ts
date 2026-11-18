import { formatDelta, formatMeasure, formatMonth } from "./format";

describe("format", () => {
  it("mostra a receita exata em reais", () => {
    expect(formatMeasure("gross_revenue", "4122460.00")).toMatch(/R\$\s4\.122\.460,00/);
  });
  it("não deixa o delta arredondado a zero com sinal", () => {
    expect(formatDelta("-0.004")).toBe("0,00%");
  });
  it("formata ticket em reais", () => {
    expect(formatMeasure("avg_ticket", "27.5")).toMatch(/R\$\s27,50/);
  });
  it("formata contagens com separador de milhar", () => {
    expect(formatMeasure("recharge_count", "12345")).toBe("12.345");
  });
  it("formata delta com sinal e trata null", () => {
    expect(formatDelta("3.5")).toBe("+3,50%");
    expect(formatDelta("-12.34")).toBe("-12,34%");
    expect(formatDelta(null)).toBe("sem base");
  });
  it("formata o mês", () => {
    expect(formatMonth("2026-10")).toMatch(/out.*2026/);
  });
});
