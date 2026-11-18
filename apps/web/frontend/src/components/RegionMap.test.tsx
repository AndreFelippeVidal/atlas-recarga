import { render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Region } from "../api";
import type { RegionStat } from "../mapStats";
import RegionMap from "./RegionMap";

// A malha real versionada em apps/web/public/geo (gerada por scripts/fetch_geo.py).
const topology = JSON.parse(
  readFileSync(resolve(process.cwd(), "../public/geo/br-uf.json"), "utf-8"),
);

describe("RegionMap com a malha real", () => {
  it("desenha as 27 UFs com geometria e destaca as fronteiras das regiões", () => {
    const { container } = render(
      <RegionMap
        topology={topology}
        measure="gross_revenue"
        stats={null}
        total={0}
        highlighted={null}
        onHighlight={() => {}}
      />,
    );
    const ufs = container.querySelectorAll("path.uf");
    expect(ufs).toHaveLength(27);
    ufs.forEach((p) => expect(p.getAttribute("d")).toMatch(/^M[-\d.,]+/));
    expect(container.querySelector("path.region-border")?.getAttribute("d")).toBeTruthy();
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("pinta cada UF pela classe de quantil da sua região e hachura a região sem valor", () => {
    const stats = new Map<Region, RegionStat>([
      ["N", { region: "N" as const, value: "100.00", rank: 2 }],
      ["SE", { region: "SE" as const, value: "900.00", rank: 1 }],
    ]);
    const { container } = render(
      <RegionMap
        topology={topology}
        measure="gross_revenue"
        stats={stats}
        total={2}
        highlighted={null}
        onHighlight={() => {}}
      />,
    );
    const fill = (uf: string) =>
      (container.querySelector(`path[aria-label^="${uf},"]`) as SVGPathElement).style.fill;
    expect(fill("PA")).toBe("var(--seq-1)"); // Norte: menor valor
    expect(fill("SP")).toBe("var(--seq-5)"); // Sudeste: maior valor
    expect(fill("BA")).toContain("#no-data"); // Nordeste: sem recargas
  });
});
