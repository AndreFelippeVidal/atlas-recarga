"""`atlas-cli validate`: confere os invariantes da SPEC-001 §6 sobre um diretório gerado.

O invariante 1 (determinismo) exige duas gerações e é coberto por teste, não por aqui.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from atlas_cli.manifest import MANIFEST_NAME, sha256_file
from atlas_cli.reference import Municipalities
from atlas_cli.scenarios import SCENARIO_IDS

FACE_VALUES = frozenset(Decimal(v) for v in (10, 15, 20, 25, 30, 40, 50, 100))
STATUSES = frozenset({"approved", "reversed"})
DEFAULT_POS = 5_000
ROWS_TOLERANCE = 0.01
UF_COUNT = 27

# RE2 (Arrow) não tem lookbehind: os padrões exigem separadores ou ancoram o valor inteiro,
# para não confundir `SUB-1234567890` ou `POS-000001` com telefone.
PII_PATTERNS = {
    "cpf": r"\d{3}\.\d{3}\.\d{3}-\d{2}|^\d{11}$",
    "email": r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}",
    "phone": (
        r"\(\d{2}\)\s?9?\d{4}-?\d{4}|\+55\s?\d{2}\s?9?\d{4}-?\d{4}"
        r"|\b\d{2}\s?9?\d{4}-\d{4}\b|^\+?(?:55)?\d{10,11}$"
    ),
}


class ValidateError(Exception):
    """Diretório sem manifest legível (exit code 2)."""


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # "ok" | "FALHA" | "pulado"
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "FALHA"


def _ok(name: str, detail: str = "") -> Check:
    return Check(name, "ok", detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, "FALHA", detail)


def _skip(name: str, detail: str) -> Check:
    return Check(name, "pulado", detail)


def load_manifest(out: Path) -> dict[str, Any]:
    path = out / MANIFEST_NAME
    if not path.is_file():
        raise ValidateError(f"{path} não existe: rode `atlas-cli generate --out {out}` antes.")
    try:
        manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidateError(f"{path} não é um JSON válido: {exc}") from exc
    for key in ("flags", "counts", "files"):
        if key not in manifest:
            raise ValidateError(f"{path} sem a chave obrigatória {key!r}")
    return manifest


def _read(path: Path) -> pa.Table:
    if path.suffix == ".csv":
        return pa_csv.read_csv(path)
    return pq.read_table(path)


def _read_many(paths: list[Path]) -> pa.Table:
    return pa.concat_tables([_read(p) for p in paths], promote_options="default")


def _check_files(out: Path, manifest: dict[str, Any]) -> Check:
    name = "manifest: sha256 dos arquivos"
    listed: dict[str, Any] = manifest["files"]
    on_disk = {
        p.relative_to(out).as_posix()
        for p in out.rglob("*")
        if p.is_file() and p.name != MANIFEST_NAME
    }
    problems = [f"ausente: {f}" for f in sorted(set(listed) - on_disk)]
    problems += [f"não listado: {f}" for f in sorted(on_disk - set(listed))]
    for rel in sorted(set(listed) & on_disk):
        if sha256_file(out / rel) != listed[rel]["sha256"]:
            problems.append(f"sha256 difere: {rel}")
    if problems:
        return _fail(name, "; ".join(problems[:5]) + (" …" if len(problems) > 5 else ""))
    return _ok(name, f"{len(listed)} arquivos")


def _check_counts(
    manifest: dict[str, Any], distributors: pa.Table, pos: pa.Table, recharges: pa.Table
) -> Check:
    name = "manifest: contagens"
    counts = manifest["counts"]
    actual = {
        "distributors": distributors.num_rows,
        "pos": pos.num_rows,
        "recharges": recharges.num_rows,
    }
    bad = [
        f"{k}: manifest {counts.get(k)} ≠ arquivos {v}"
        for k, v in actual.items()
        if counts.get(k) != v
    ]
    return _fail(name, "; ".join(bad)) if bad else _ok(name)


def _inv2_clean(manifest: dict[str, Any], tables: dict[str, pa.Table]) -> Check:
    name = "invariante 2: sem nulos, duplicados, FKs órfãs nem valores fora da face"
    if manifest["flags"].get("scenarios") or any(
        day.get("scenarios_enabled") for day in manifest.get("incremental", {}).values()
    ):
        return _skip(name, "só vale com --scenarios none")
    problems: list[str] = []
    for entity, table in tables.items():
        # `pos.closed_date` é nullable por definição (§4)
        columns = [c for c in table.column_names if (entity, c) != ("pos", "closed_date")]
        nulls = sum(table[c].null_count for c in columns)
        if nulls:
            problems.append(f"{entity}: {nulls} nulos")
    recharges, pos = tables["recharges"], tables["pos"]
    for table, key in (
        (recharges, "recharge_id"),
        (pos, "pos_id"),
        (tables["distributors"], "distributor_id"),
    ):
        if len(pc.unique(table[key])) != table.num_rows:
            problems.append(f"{key} duplicado")
    orphans = pc.sum(pc.invert(pc.is_in(recharges["pos_id"], value_set=pos["pos_id"]))).as_py() or 0
    if orphans:
        problems.append(f"{orphans} recargas com pos_id órfão")
    orphan_dist = (
        pc.sum(
            pc.invert(
                pc.is_in(pos["distributor_id"], value_set=tables["distributors"]["distributor_id"])
            )
        ).as_py()
        or 0
    )
    if orphan_dist:
        problems.append(f"{orphan_dist} PDVs com distributor_id órfão")
    amounts = {Decimal(str(v)) for v in pc.unique(recharges["amount_brl"]).to_pylist()}
    if amounts - FACE_VALUES:
        problems.append(f"valores fora da face: {sorted(amounts - FACE_VALUES)}")
    statuses = set(pc.unique(recharges["status"]).to_pylist())
    if statuses - STATUSES:
        problems.append(f"status inválido: {sorted(statuses - STATUSES)}")
    return _fail(name, "; ".join(problems)) if problems else _ok(name)


def _inv3_municipalities(pos: pa.Table, municipalities: Municipalities) -> Check:
    name = "invariante 3: municípios dos PDVs existem na referência IBGE"
    known = pa.array(municipalities.code, pa.string())
    codes = pos["municipality_ibge_code"].cast(pa.string())
    unknown = pc.sum(pc.invert(pc.is_in(codes, value_set=known))).as_py() or 0
    return _fail(name, f"{unknown} PDVs com código desconhecido") if unknown else _ok(name)


def _inv4_ufs(manifest: dict[str, Any], pos: pa.Table, municipalities: Municipalities) -> Check:
    name = "invariante 4: as 27 UFs têm PDV"
    n_pos = manifest["flags"].get("pos", 0)
    if n_pos < DEFAULT_POS:
        return _skip(name, f"só vale com --pos ≥ {DEFAULT_POS} (gerado com {n_pos})")
    uf_by_code = dict(zip(municipalities.code, municipalities.uf, strict=True))
    present = {uf_by_code.get(c) for c in pc.unique(pos["municipality_ibge_code"]).to_pylist()}
    missing = sorted(set(municipalities.uf) - present)
    if missing or len(set(municipalities.uf)) != UF_COUNT:
        return _fail(name, f"UFs sem PDV: {missing}")
    return _ok(name)


def _inv5_total(manifest: dict[str, Any], recharges: pa.Table) -> Check:
    name = "invariante 5: total de recargas dentro de ±1% de --rows"
    if manifest.get("incremental"):
        days = ", ".join(sorted(manifest["incremental"]))
        return _skip(name, f"há partição incremental ({days}); o total deixa de seguir --rows")
    wanted = manifest["flags"]["rows"]
    gap = abs(recharges.num_rows - wanted) / wanted
    detail = f"{recharges.num_rows} de {wanted} ({gap:.2%})"
    return _fail(name, detail) if gap > ROWS_TOLERANCE else _ok(name, detail)


def _inv6_pii(tables: dict[str, pa.Table]) -> Check:
    name = "invariante 6: nenhum CPF, e-mail ou telefone com formato real"
    hits: list[str] = []
    for entity, table in tables.items():
        for field in table.schema:
            if not (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)):
                continue
            for kind, pattern in PII_PATTERNS.items():
                found = pc.sum(pc.match_substring_regex(table[field.name], pattern)).as_py() or 0
                if found:
                    hits.append(f"{entity}.{field.name}: {found} valores com formato de {kind}")
    return _fail(name, "; ".join(hits)) if hits else _ok(name)


def validate_directory(out: Path, municipalities: Municipalities) -> list[Check]:
    manifest = load_manifest(out)
    checks = [_check_files(out, manifest)]
    if checks[0].failed:
        return checks  # arquivos adulterados ou faltando: ler as tabelas não ajuda
    suffix = ".csv" if manifest["flags"].get("format") == "csv" else ".parquet"
    recharge_files = sorted((out / "recharges").glob(f"dt=*/part-*{suffix}"))
    if not recharge_files:
        return [*checks, _fail("recharges", "nenhum arquivo em recharges/")]
    tables = {
        "distributors": _read(out / "distributors" / f"distributors{suffix}"),
        "pos": _read(out / "pos" / f"pos{suffix}"),
        "recharges": _read_many(recharge_files),
    }
    unknown = set(manifest.get("scenarios", {})) - set(SCENARIO_IDS)
    steps: list[Callable[[], Check]] = [
        lambda: _check_counts(manifest, tables["distributors"], tables["pos"], tables["recharges"]),
        lambda: _inv2_clean(manifest, tables),
        lambda: _inv3_municipalities(tables["pos"], municipalities),
        lambda: _inv4_ufs(manifest, tables["pos"], municipalities),
        lambda: _inv5_total(manifest, tables["recharges"]),
        lambda: _inv6_pii(tables),
    ]
    checks.extend(step() for step in steps)
    if unknown:
        checks.append(_fail("manifest: cenários", f"desconhecidos: {sorted(unknown)}"))
    return checks
