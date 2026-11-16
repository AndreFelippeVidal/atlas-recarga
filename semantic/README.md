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
