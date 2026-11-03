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

### Testes de unidade e de integração

- `pytest -q` roda só os testes de **unidade** (marcador `unidade`, automático para tudo
  fora de `tests/integracao/`): sem Databricks, no CI de PR e no pre-commit.
- Os testes de **integração** (`tests/integracao/`, marcador `integracao`) rodam no
  workflow `integracao.yml`, à noite de segunda a sexta ou à mão (*Run workflow*). Ele
  implanta o target `ci`, carrega a agenda fictícia v1 e a v2, confere os dados e destrói
  tudo no fim (ADR 0005). Os totais esperados ficam em `tests/integracao/esperado.py`.
- Mudou o gerador, o `fontes.yml` ou a silver da agenda? Rode o workflow no PR (*Run
  workflow* na branch) e atualize o `esperado.py` se os totais mudarem de propósito.
- Para rodar na sua máquina: `databricks bundle deploy -t ci`, `databricks bundle summary
  -t ci -o json > recursos-ci.json` e os passos do workflow. O destroy do `ci` só roda no
  GitHub Actions (localmente o hook bloqueia qualquer `bundle destroy`).

## Implantação

- **dev (Free Edition):** `databricks bundle deploy -t dev` e `databricks bundle run ... -t dev`
  pedem confirmação (regra `ask`). Defina `BUNDLE_VAR_alert_email` antes do deploy. O
  agendamento do job fica pausado em dev: a carga roda quando alguém manda.
- **ci (Free Edition):** usado só pelos testes de integração, com o projeto `<projeto>_ci`
  e estado de deploy próprio; nunca toca nos schemas do dev.
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
## Cadeia de suprimentos

- **Versões fixas, num lugar só por tipo:**
  - pacotes do Databricks (pipeline e jobs): `requirements-runtime.txt`, instalado com
    `-r`; o `requirements-dev.txt` o inclui e acrescenta as ferramentas de desenvolvimento;
  - actions: pelo SHA do commit, com a versão em comentário;
  - pre-commit: `rev` pelo SHA, com `# frozen: vX.Y.Z`;
  - gitleaks: a mesma versão no job `segredos` do CI (com o SHA-256 do binário) e no
    pre-commit; ao atualizar, troque nos dois lugares (um teste confere).
- **Dependabot** abre os PRs de atualização toda semana, só de versões publicadas há pelo
  menos 14 dias (`cooldown`). Cada PR passa pelo CI e só entra com o merge do responsável.
- **pre-commit**: rode `pre-commit install` uma vez por clone; os hooks repetem o CI
  (ruff, YAML, JSON, espaços, chave privada, segredos) antes de cada commit.
- **Segurança do repositório**: `SECURITY.md` explica o reporte privado de
  vulnerabilidades; `CODEOWNERS` define quem revisa; o template de PR traz o checklist.

## Lint

- Regras do ruff em `ruff.toml` (E, W, F, I, B, UP, BLE, RUF). Não use `# noqa` sem
  necessidade nem `except Exception`: capture a exceção específica.
