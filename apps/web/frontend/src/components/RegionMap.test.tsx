import { render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { buildGeometry } from "../geoShapes";
import type { Stat } from "../mapStats";
import RegionMap from "./RegionMap";

// A malha real versionada em apps/web/public/geo (gerada por scripts/fetch_geo.py).
const read = (rel: string) => JSON.parse(readFileSync(resolve(process.cwd(), rel), "utf-8"));
const topology = read("../public/geo/br-uf.json");
const brazil = buildGeometry(topology, null, { level: "brazil" });
if (!brazil) throw new Error("malha do Brasil não construída");

const noop = () => {};
const base = {
  geometry: brazil,
  measure: "gross_revenue" as const,
  label: "Mapa",
  interactive: true,
  highlighted: null,
  onHighlight: noop,
  onSelect: noop,
};

describe("RegionMap com a malha real", () => {
  it("desenha as 27 UFs com geometria e destaca as fronteiras das regiões", () => {
    const { container } = render(<RegionMap {...base} stats={null} />);
    const ufs = container.querySelectorAll("path.uf");
    expect(ufs).toHaveLength(27);
    ufs.forEach((p) => expect(p.getAttribute("d")).toMatch(/^M[-\d.,]+/));
    expect(container.querySelector("path.region-border")?.getAttribute("d")).toBeTruthy();
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("pinta cada UF pela classe de quantil da sua região e hachura a região sem valor", () => {
    const stats = new Map<string, Stat>([
      ["N", { id: "N", name: "Norte", value: "100.00", rank: 2 }],
      ["SE", { id: "SE", name: "Sudeste", value: "900.00", rank: 1 }],
    ]);
    const { container } = render(<RegionMap {...base} stats={stats} />);
    const fill = (uf: string) =>
      (container.querySelector(`path[aria-label^="${uf},"]`) as SVGPathElement).style.fill;
    expect(fill("PA")).toBe("var(--seq-1)"); // Norte: menor valor
    expect(fill("SP")).toBe("var(--seq-5)"); // Sudeste: maior valor
    expect(fill("BA")).toContain("#no-data"); // Nordeste: sem recargas
  });

  it("no foco de uma região desenha só as UFs dela e sem fronteira de região", () => {
    const north = buildGeometry(topology, null, { level: "region", region: "N" });
    expect(north?.shapes.map((s) => s.id).sort()).toEqual(
      ["AC", "AM", "AP", "PA", "RO", "RR", "TO"].sort(),
    );
    expect(north?.regionBorders).toBe("");
  });

  it("no foco de uma UF desenha os municípios da malha da UF", () => {
    const pa = buildGeometry(topology, read("../public/geo/mun/PA.json"), {
      level: "uf",
      uf: "PA",
      region: "N",
    });
    expect(pa?.shapes).toHaveLength(144);
    expect(pa?.shapes.every((s) => /^15\d{5}$/.test(s.statKey))).toBe(true);
  });

  it("não desenha os municípios antes de a malha chegar", () => {
    expect(buildGeometry(topology, null, { level: "uf", uf: "PA", region: "N" })).toBeNull();
  });
});
