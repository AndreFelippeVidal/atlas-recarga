import { geoMercator, geoPath } from "d3-geo";
import { feature, mesh } from "topojson-client";
import type { GeometryCollection, GeometryObject, Topology } from "topojson-specification";
import type { MapFocus, Region } from "./api";
import { REGION_NAMES } from "./regions";

export const WIDTH = 600;
export const HEIGHT = 640;

interface UfProps {
  uf: string;
  region: Region;
}
interface MunProps {
  municipality_ibge_code: string;
}

// Um polígono clicável. `statKey` liga o polígono ao valor da API (região, UF ou código IBGE).
export interface Shape {
  id: string;
  statKey: string;
  title: string;
  ariaName: string;
  d: string;
}

export interface Geometry {
  shapes: Shape[];
  regionBorders: string;
  outline: string;
}

// Geometria do foco atual, já enquadrada (fitSize) no bounding box do que aparece: no foco de
// região ou de UF as demais geometrias somem e o recorte fica centralizado (SPEC-007 §4).
// Devolve null enquanto a malha do nível ainda não chegou.
export function buildGeometry(
  ufTopology: unknown,
  munTopology: unknown,
  focus: MapFocus,
): Geometry | null {
  if (focus.level === "uf") {
    if (!munTopology) return null;
    const topo = munTopology as Topology;
    const obj = topo.objects.municipalities as GeometryCollection<MunProps>;
    const collection = feature(topo, obj);
    const path = geoPath(geoMercator().fitSize([WIDTH, HEIGHT], collection));
    return {
      shapes: collection.features.map((f) => {
        const code = f.properties.municipality_ibge_code;
        return { id: code, statKey: code, title: code, ariaName: code, d: path(f) ?? "" };
      }),
      regionBorders: "",
      outline: path(mesh(topo, obj, (a, b) => a === b)) ?? "",
    };
  }
  if (!ufTopology) return null;
  const topo = ufTopology as Topology;
  const obj = topo.objects.uf as GeometryCollection<UfProps>;
  const geometries = obj.geometries.filter(
    (g) =>
      focus.level === "brazil" ||
      (g.properties as Partial<UfProps> | null | undefined)?.region === focus.region,
  );
  const subset: GeometryCollection<UfProps> = { type: "GeometryCollection", geometries };
  const collection = feature(topo, subset);
  const path = geoPath(geoMercator().fitSize([WIDTH, HEIGHT], collection));
  const regionOf = (g: GeometryObject): string | undefined =>
    (g.properties as Partial<UfProps> | null | undefined)?.region;
  return {
    shapes: collection.features.map((f) => {
      const { uf, region } = f.properties;
      return focus.level === "brazil"
        ? {
            id: uf,
            statKey: region,
            title: REGION_NAMES[region],
            ariaName: `${uf}, região ${REGION_NAMES[region]}`,
            d: path(f) ?? "",
          }
        : { id: uf, statKey: uf, title: uf, ariaName: uf, d: path(f) ?? "" };
    }),
    regionBorders:
      focus.level === "brazil"
        ? (path(mesh(topo, subset, (a, b) => regionOf(a) !== regionOf(b))) ?? "")
        : "",
    outline: path(mesh(topo, subset, (a, b) => a === b)) ?? "",
  };
}
