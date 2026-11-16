"""Máquina de estados do lote de comissão e job `atlas_commission_review` (SPEC-003 §4, P8.6).

Uma pessoa dispara o job com `batch_id`, `decision` (`submit`, `approve` ou `reject`) e, na
rejeição, `justification`. Cada execução faz **uma** transição e a grava em
`commission.batch_events` (append-only). Nenhum agente, MCP ou app executa este job (ADR-0010).
Sem IA: só regras.

| decision | de                  | para              | quem                              |
|----------|---------------------|-------------------|-----------------------------------|
| submit   | draft               | under_review      | sistema; exige reconciliação passed |
| approve  | under_review        | analyst_approved  | grupo `atlas_commission_analysts`   |
| approve  | analyst_approved    | approved          | diretora (`..._directors`), ator ≠ analista |
| reject   | under_review        | rejected          | analista; justificativa ≥ 20 caracteres |
| reject   | analyst_approved    | rejected          | diretora; justificativa ≥ 20 caracteres |

O lock e a remessa (`approved -> locked`) são da P8.7. A versão `vN+1` depois de uma rejeição
também não nasce aqui: o rascunho só cria a `v1` (ver README).

**Ator.** O job roda como o dono do bundle, então `current_user()` não é quem decidiu. O ator
é o `creator_user_name` da execução (`jobs.get_run`), que o usuário não consegue informar. O
pertencimento aos grupos vem da API de usuários (SCIM), pelo mesmo motivo.

**Segregação de funções.** Se o diretor é o mesmo ator que aprovou como analista, a transição
falha com `SEGREGATION_OF_DUTIES_VIOLATION` e a tentativa fica em `batch_events` com
`to_status = 'denied'` (não conta como aprovação). Contingência da SPEC-003 §9:
`allow_same_approver_demo=true` deixa passar, grava `role = 'demo_override'` e marca
`batches.demo_mode = true`.

**Escritas.** Não são uma transação. Ordem: o `status` do lote com `WHERE status = <de>`
(compare-and-set; se nenhuma linha mudar, o job falha) e só então o evento. Assim todo evento
corresponde a uma transição aplicada. Se a gravação do evento falhar depois do status, o job
falha dizendo que o evento precisa ser registrado à mão. A tentativa negada (`denied`) só
grava o evento.
"""

from __future__ import annotations

import importlib
import re
import sys
from dataclasses import dataclass
from typing import Any

ANALYSTS_GROUP = "atlas_commission_analysts"
DIRECTORS_GROUP = "atlas_commission_directors"
MIN_JUSTIFICATION = 20
DECISIONS = ("submit", "approve", "reject")
DENIED = "denied"
_GROUP_OF = {"analyst": ANALYSTS_GROUP, "director": DIRECTORS_GROUP}

_USER_NAME = re.compile(r"^[A-Za-z0-9._%+@-]+$")  # sem aspas nem barras: entra num filtro SCIM
_BATCH_ID = re.compile(r"^COM-\d{4}-(0[1-9]|1[0-2])-(v\d+|ADJ-\d+)$")

SEGREGATION_OF_DUTIES_VIOLATION = "SEGREGATION_OF_DUTIES_VIOLATION"
JUSTIFICATION_REQUIRED = "JUSTIFICATION_REQUIRED"
INVALID_TRANSITION = "INVALID_TRANSITION"
RECONCILIATION_NOT_PASSED = "RECONCILIATION_NOT_PASSED"
ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
INVALID_REQUEST = "INVALID_REQUEST"


@dataclass(frozen=True)
class Transition:
    """Um evento de `batch_events` (a transição feita ou a tentativa negada)."""

    from_status: str
    to_status: str
    role: str
    justification: str | None = None
    demo_override: bool = False


class ReviewError(Exception):
    """Falha de regra, com o código da SPEC-003. `audit` é o evento a gravar mesmo assim."""

    def __init__(self, code: str, message: str, audit: Transition | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.audit = audit


@dataclass(frozen=True)
class BatchState:
    status: str
    reconciliation_status: str | None
    analyst_actor: str | None  # quem fez `under_review -> analyst_approved`


@dataclass(frozen=True)
class Request:
    decision: str
    actor: str
    groups: frozenset[str]
    justification: str = ""
    allow_same_approver_demo: bool = False


def _clean(justification: str) -> str:
    return justification.strip()


def decide(state: BatchState, request: Request) -> Transition:
    """Valida o pedido contra o estado do lote e devolve o evento. Função pura."""
    if request.decision not in DECISIONS:
        raise ReviewError(INVALID_REQUEST, f"decision deve ser uma de {DECISIONS}")
    status = state.status
    text = _clean(request.justification)

    if request.decision == "submit":
        if status != "draft":
            raise ReviewError(INVALID_TRANSITION, f"submit exige draft; o lote está em {status}")
        if state.reconciliation_status != "passed":
            raise ReviewError(
                RECONCILIATION_NOT_PASSED,
                f"reconciliação está {state.reconciliation_status!r}; só passed libera o lote",
            )
        return Transition("draft", "under_review", "system", text or None)

    if request.decision == "reject":
        role = _reject_role(_role_for_review_status(status, "reject"), request)
        if len(text) < MIN_JUSTIFICATION:
            raise ReviewError(
                JUSTIFICATION_REQUIRED,
                f"a rejeição exige justificativa com {MIN_JUSTIFICATION}+ caracteres",
            )
        return Transition(status, "rejected", role, text)

    # approve
    role = _role_for_review_status(status, "approve")
    _require_group(request, role)
    if status == "under_review":
        return Transition("under_review", "analyst_approved", "analyst", text or None)

    same_actor = (
        state.analyst_actor is not None and request.actor.lower() == state.analyst_actor.lower()
    )
    if same_actor and not request.allow_same_approver_demo:
        raise ReviewError(
            SEGREGATION_OF_DUTIES_VIOLATION,
            "quem aprovou como analista não pode aprovar como diretora",
            audit=Transition(
                "analyst_approved",
                DENIED,
                "director",
                f"{SEGREGATION_OF_DUTIES_VIOLATION}: tentativa de aprovar como diretora",
            ),
        )
    if same_actor:
        return Transition(
            "analyst_approved", "approved", "demo_override", text or None, demo_override=True
        )
    return Transition("analyst_approved", "approved", "director", text or None)


def _role_for_review_status(status: str, decision: str) -> str:
    if status == "under_review":
        return "analyst"
    if status == "analyst_approved":
        return "director"
    raise ReviewError(INVALID_TRANSITION, f"{decision} não vale para um lote em {status}")


def _reject_role(stage_role: str, request: Request) -> str:
    """SPEC-003 §4: `* -> rejected` é de quem for analista **ou** diretora, em qualquer etapa."""
    other = "director" if stage_role == "analyst" else "analyst"
    for role in (stage_role, other):
        if _GROUP_OF[role] in request.groups:
            return role
    raise ReviewError(
        ROLE_NOT_ALLOWED,
        f"{request.actor} não é membro de {ANALYSTS_GROUP} nem de {DIRECTORS_GROUP}",
    )


def _require_group(request: Request, role: str) -> None:
    group = _GROUP_OF[role]
    if group not in request.groups:
        raise ReviewError(ROLE_NOT_ALLOWED, f"{request.actor} não é membro de {group}")


# --- IO (workspace) ---------------------------------------------------------------------


def _draft() -> Any:
    return importlib.import_module("commission.draft")


def load_state(spark: Any, catalog: str, batch_id: str) -> BatchState:
    batches = f"{catalog}.commission.batches"
    events = f"{catalog}.commission.batch_events"
    recon = f"{catalog}.commission.reconciliation"
    header = spark.sql(
        f"SELECT status FROM {batches} WHERE batch_id = :b",  # noqa: S608
        args={"b": batch_id},
    ).first()
    if header is None:
        raise ReviewError(INVALID_REQUEST, f"{batch_id} não existe")
    r = spark.sql(
        f"SELECT status FROM {recon} WHERE batch_id = :b",  # noqa: S608
        args={"b": batch_id},
    ).first()
    a = spark.sql(
        f"SELECT actor FROM {events} WHERE batch_id = :b AND to_status = 'analyst_approved' "  # noqa: S608
        "ORDER BY event_ts_utc DESC LIMIT 1",
        args={"b": batch_id},
    ).first()
    return BatchState(
        status=header["status"],
        reconciliation_status=None if r is None else r["status"],
        analyst_actor=None if a is None else a["actor"],
    )


def append_event(spark: Any, catalog: str, batch_id: str, actor: str, t: Transition) -> None:
    spark.sql(
        f"INSERT INTO {catalog}.commission.batch_events "
        "(event_id, batch_id, from_status, to_status, actor, role, justification, event_ts_utc) "
        "SELECT uuid(), :b, :f, :t, :a, :r, :j, current_timestamp()",
        args={
            "b": batch_id,
            "f": t.from_status,
            "t": t.to_status,
            "a": actor,
            "r": t.role,
            "j": t.justification,
        },
    )


def apply_status(spark: Any, catalog: str, batch_id: str, t: Transition) -> None:
    demo = ", demo_mode = true" if t.demo_override else ""
    result = spark.sql(
        f"UPDATE {catalog}.commission.batches SET status = :t{demo} "  # noqa: S608
        "WHERE batch_id = :b AND status = :f",
        args={"b": batch_id, "t": t.to_status, "f": t.from_status},
    ).first()
    if result is None or int(result["num_affected_rows"]) != 1:
        raise RuntimeError(f"{batch_id} mudou de estado durante a execução; nada foi aplicado")


def lookup_actor_and_groups(run_id: int) -> tuple[str, frozenset[str]]:
    """Quem disparou a execução e os grupos dessa pessoa (não vêm de parâmetro do usuário)."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    run = w.jobs.get_run(run_id=run_id)
    actor = run.creator_user_name
    if not actor:
        raise ReviewError(INVALID_REQUEST, "a execução não informa quem a disparou")
    if not _USER_NAME.fullmatch(actor):
        raise ReviewError(INVALID_REQUEST, f"nome de usuário inesperado: {actor!r}")
    found = list(w.users.list(filter=f'userName eq "{actor}"', attributes="userName,groups,active"))
    if not found or found[0].active is False:
        raise ReviewError(INVALID_REQUEST, f"usuário {actor} não encontrado ou inativo")
    groups = frozenset(g.display for g in (found[0].groups or []) if g.display)
    return actor, groups


def review(
    spark: Any,
    catalog: str,
    batch_id: str,
    request: Request,
) -> Transition:
    draft = _draft()
    draft.check_identifier(catalog, "catalog name")
    if not _BATCH_ID.fullmatch(batch_id):
        raise ReviewError(INVALID_REQUEST, f"batch_id inválido: {batch_id!r}")
    state = load_state(spark, catalog, batch_id)
    try:
        transition = decide(state, request)
    except ReviewError as err:
        if err.audit is not None:  # a tentativa negada fica na trilha
            append_event(spark, catalog, batch_id, request.actor, err.audit)
        raise
    # Status primeiro, com compare-and-set: um evento só existe para uma transição aplicada
    # (um evento órfão num log append-only não se corrige e inflaria a contagem de aprovações).
    apply_status(spark, catalog, batch_id, transition)
    try:
        append_event(spark, catalog, batch_id, request.actor, transition)
    except Exception as err:
        raise RuntimeError(
            f"{batch_id} foi para {transition.to_status}, mas o evento NÃO foi gravado; "
            f"registre manualmente o evento de {request.actor} antes de seguir"
        ) from err
    return transition


def main(
    catalog: str,
    root: str,
    batch_id: str,
    decision: str,
    justification: str,
    run_id: str,
    allow_same_approver_demo: str = "false",
) -> None:
    from pyspark.sql import SparkSession  # só existe no workspace

    if root not in sys.path:
        sys.path.insert(0, root)
    actor, groups = lookup_actor_and_groups(int(run_id))
    request = Request(
        decision=decision.strip().lower(),
        actor=actor,
        groups=groups,
        justification=justification,
        allow_same_approver_demo=allow_same_approver_demo.strip().lower() == "true",
    )
    spark: Any = SparkSession.builder.getOrCreate()
    t = review(spark, catalog, batch_id, request)
    print(f"{batch_id}: {t.from_status} -> {t.to_status} por {actor} ({t.role})")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(*sys.argv[1:])
