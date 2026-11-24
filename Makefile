# Atalhos de operação (P13.1). Os checks de código ficam nos comandos do CLAUDE.md.
.PHONY: apps-start

# Religa os 3 Apps (auto-stop de 24 h, ADR-0009) e espera os healthchecks.
# PROFILE é obrigatório e não tem padrão: escolha o perfil do seu .databrickscfg.
#   make apps-start PROFILE=andrevidal
apps-start:
	@test -n "$(PROFILE)" || { echo "Informe o perfil: make apps-start PROFILE=<perfil>" >&2; exit 2; }
	uv run python scripts/apps_start.py --profile "$(PROFILE)"
