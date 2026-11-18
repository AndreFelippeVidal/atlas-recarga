import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Regra da SPEC-007 §4: na escala divergente, cor mais escura = variação mais extrema, seja
// queda ou alta, em tema claro e escuro (o neutro é o mais claro; as pontas, as mais escuras).
const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf-8");

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function div(block: string): number[] {
  return [1, 2, 3, 4, 5].map((n) => {
    const m = block.match(new RegExp(`--div-${n}:\\s*(#[0-9a-fA-F]{6})`));
    if (!m) throw new Error(`--div-${n} ausente`);
    return luminance(m[1]);
  });
}

const dark = css.indexOf("prefers-color-scheme: dark");
const themes = { claro: css.slice(0, dark), escuro: css.slice(dark) };

describe.each(Object.entries(themes))("paleta divergente, tema %s", (_name, block) => {
  const [d1, d2, d3, d4, d5] = div(block);

  it("escurece do neutro para as pontas, nos dois sentidos", () => {
    expect(d3).toBeGreaterThan(d2);
    expect(d2).toBeGreaterThan(d1);
    expect(d3).toBeGreaterThan(d4);
    expect(d4).toBeGreaterThan(d5);
  });

  it("queda e alta têm a mesma intensidade (luminâncias próximas)", () => {
    expect(Math.abs(d1 - d5)).toBeLessThan(0.07);
    expect(Math.abs(d2 - d4)).toBeLessThan(0.07);
  });
});
