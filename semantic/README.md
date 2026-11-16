# semantic

Metric views em YAML (`atlas.semantic`). Governado pela [SPEC-004](../docs/specs/004-metric-views/spec.md). Path sensível: CODEOWNERS.

## Ordem do deploy (metric views x Genie Space)

O Genie Space `atlas_recarga` (`databricks.yml`) lê `mv_recharges` e `mv_commission`, e o
`bundle deploy` **falha** se uma delas ainda não existe (`Table ... does not exist`, 403
`PERMISSION_DENIED`). Quem cria as views é o job `atlas_semantic_deploy`, que só existe depois do
deploy. Então, **ao adicionar uma metric view nova ou num catálogo vazio**:

```bash
databricks bundle deploy -t dev --profile <perfil>      # pode falhar no Genie; os arquivos já subiram
databricks bundle run atlas_semantic_deploy -t dev --profile <perfil>   # cria as views
databricks bundle deploy -t dev --profile <perfil>      # agora o Genie encontra as tabelas
```

Depois da primeira vez, um deploy basta. A mesma ordem vale para `-t demo` (runbook da P13).

## UC functions do agente (P10.1)

O job `atlas_semantic_deploy` tem uma segunda task, `apply_agent_functions`
(`semantic/apply_functions.py`), que cria `fn_list_metrics`, `fn_metric_by_region` e
`fn_compare_months` em `<catalog>.semantic` depois das metric views (SPEC-005 §3). O DDL é gerado
do `mv_recharges.yaml`: medidas, dimensões e descrições têm uma definição só. Medida ou nível fora
da lista falha com `INVALID_MEASURE` ou `INVALID_LEVEL`. Os leitores recebem `EXECUTE` em
`semantic` (`setup_workspace.py`); conferência no `dev` com `scripts/check_agent_functions.py`. O `EXECUTE` só vale depois de rodar
`scripts/setup_workspace.py` de novo (com `--reader` por principal, ADR-0016).
