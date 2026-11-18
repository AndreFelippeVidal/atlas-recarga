import { render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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
});
