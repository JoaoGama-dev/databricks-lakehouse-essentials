# Fluxo de trabalho

## Branch, commit e pull request

- Nunca trabalhe na `main`: ela é protegida (PR obrigatório, CI verde, sem push forçado),
  e o hook `proteger_comandos.py` bloqueia push direto nela.
- Uma branch e um PR por entrega (ex.: uma fase do `docs/plano-padrao-senior.md`), com
  commits pequenos por item.
- Mensagens de commit em português, com a linha `Co-Authored-By` quando o Claude
  participar. Para mensagens longas ou que citem caminhos de dados, use `git commit -F`.

## Validação

O Claude **roda** e mostra a saída, antes de dizer que terminou:

```
ruff check .
pytest -q
databricks bundle validate -t dev
```

Esses comandos estão liberados em `.claude/settings.json`. O hook `lint_apos_edicao.py`
também roda o ruff em cada `.py` editado.

## Implantação

- **dev (Free Edition):** `databricks bundle deploy -t dev` e `databricks bundle run ... -t dev`
  pedem confirmação (regra `ask`). Defina `BUNDLE_VAR_alert_email` antes do deploy.
- **prod (Azure do cliente):** só pelo workflow `deploy.yml` no GitHub, com aprovação do
  environment `prod`. Qualquer comando local com `-t prod` é bloqueado (deny e hook).
- Nada é alterado à mão em produção.

## Agentes

O fluxo de uma mudança grande e o papel de cada subagente estão no `CLAUDE.md`. Os
subagentes ficam em `.claude/agents/` e as skills em `.claude/skills/`.

## Ambiente e limitações conhecidas

- **Windows + PowerShell** no desenvolvimento; o CI roda em Linux. Scripts e hooks são em
  Python, só biblioteca padrão.
- Os hooks chamam `python`: no Linux, garanta que o comando exista (pacote
  `python-is-python3` ou um alias).
- **Sandbox do Claude Code:** não roda no Windows nativo (só macOS, Linux e WSL2), então
  não está ativado. A proteção vem das permissões e dos hooks.
- Versões de ferramentas fixadas em `requirements-dev.txt` e nos workflows. Atualize por
  PR, com versões publicadas há pelo menos 2 semanas.

## Lint

- Regras do ruff em `ruff.toml` (E, W, F, I, B, UP, BLE, RUF). Não use `# noqa` sem
  necessidade nem `except Exception`: capture a exceção específica.
