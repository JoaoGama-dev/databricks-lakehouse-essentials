# Desenvolvimento: IA, CI/CD e cadeia de suprimentos

Como o projeto é desenvolvido e entregue. O dia a dia (branch, PR, validação,
implantação) está em [`docs/padroes/fluxo-de-trabalho.md`](padroes/fluxo-de-trabalho.md).

## Desenvolvimento com Claude Code

O projeto vem com uma camada de IA versionada em `.claude/`, para que o uso de agentes
siga as mesmas regras do time ([ADR 0012](adr/0012-guardrails-do-claude-code.md)):

| Peça | O que faz |
|---|---|
| `.claude/settings.json` | **permissões**: libera lint, testes e `bundle validate`; pede confirmação para deploy, run, commit e push; **nega** produção, `destroy`, push forçado e leitura de `.env` e dados reais |
| `.claude/hooks/` | **guardrails determinísticos** em Python: bloqueiam comandos de produção e destroy, push na `main`, leitura de dados reais e tokens; rodam o ruff em todo `.py` editado; restringem o que o QA e o documentador editam |
| `scripts/perfilar_dados.py` | **perfil sem dados pessoais**: o modelo entende a estrutura de um arquivo do cliente sem ver nomes, CPFs ou telefones |
| `.claude/agents/` | 6 subagentes: arquiteto, engenheiro, QA, DevOps, revisor de segurança e documentador |
| `.claude/skills/` | 8 skills: novo cliente, nova fonte, novo indicador, revisão de qualidade, implantar em dev, revisar PR, ADR e entrega |
| `tests/evals/` | casos de avaliação das skills críticas, com dados fictícios |

O princípio: **o que não pode falhar vira permissão ou hook; o que é orientação fica no
`CLAUDE.md` ou numa skill.** Os padrões estão em `docs/padroes/` e os hooks são testados
em `tests/nucleo/test_hooks.py`.

### Fluxo de uma mudança grande

```mermaid
flowchart TD
    pedido(["Pedido: cliente novo, fonte, indicador ou fase do plano"])
    arq["arquiteto-dados<br/>propõe fontes.yml, regras, modelo estrela<br/>(lê só o perfil dos dados)"]
    ok1{"Aprovação do João"}
    eng["engenheiro-dados<br/>implementa config, SQL, Python e testes"]
    qa["qa-dados<br/>lint, testes, bundle validate, dicionário, nomes"]
    seg["revisor-seguranca<br/>segredos, dados pessoais, permissões, dependências"]
    ops["devops-dados<br/>deploy e execução só em dev"]
    doc["documentador<br/>README, roteiro, ADRs, CHANGELOG"]
    pr["Pull request + CI<br/>(testes, validar_bundle, segredos)"]
    ok2{"Aprovação do João"}
    merge(["Merge na main"])
    prod["Produção: só pelo workflow deploy.yml,<br/>com aprovação no environment prod"]

    pedido --> arq --> ok1
    ok1 -- "aprovado" --> eng
    ok1 -- "ajustar" --> arq
    eng --> qa
    qa -- "falhou" --> eng
    qa -- "ok" --> seg
    seg -- "bloqueante" --> eng
    seg -- "ok" --> ops --> doc --> pr --> ok2
    ok2 -- "aprovado" --> merge
    ok2 -- "ajustar" --> eng
    merge -.-> prod
```

Nenhum agente implanta em produção: o `-t prod` é negado nas permissões e bloqueado pelo
hook, e o deploy de produção só acontece pelo GitHub Actions
([ADR 0011](adr/0011-deploy-de-producao-por-oidc.md)).

## CI/CD

| Workflow | Gatilho | O que faz |
|---|---|---|
| `ci.yml` | pull request para a `main` | `ruff check .`, `pytest -q` (só testes de unidade, em `tests/nucleo/` e `tests/projeto/`; inclui o contrato do `fontes.yml` e da gold, a checagem de que o núcleo não cita o projeto e a documentação), `databricks bundle validate -t dev` e varredura de segredos no histórico (gitleaks) |
| `integracao.yml` | 1h de segunda a sexta e manual (nunca em PR) | implanta o target `ci`, faz duas rodadas de carga com a agenda fictícia (v1; depois v2, v6, v7 e v5), confere os dados (`tests/projeto/integracao/test_carga.py`) e destrói tudo no fim (cerca de 15 minutos; timeout de 30) |
| `deploy.yml` | manual (`workflow_dispatch`) | `bundle validate` e `bundle deploy -t prod` no environment `prod`, com login OIDC |

- **Testes de integração** ([ADR 0005](adr/0005-testes-de-integracao.md)): o target `ci`
  usa o projeto `<projeto>_ci`, com os quatro schemas (`_ci_bronze`, `_ci_silver`,
  `_ci_gold` e `_ci_monitoramento`) e estado de deploy próprios, sem tocar no dev. As
  asserções conferem as versões da silver (vigentes, total e fechadas), descartes e alertas
  por regra, chaves sem nulo e sem duplicata, que o retrato privado não aparece no catálogo,
  a fato com uma linha por entrevista vigente, a view do painel com o mesmo total da fato e
  as tags `camada` e `tipo`, e o log da carga (`mon_log_execucao`) com job, tarefas e
  tabelas, duração legível e a última atualização anterior preenchida na rodada 2.
- **Duas rodadas** ([ADR 0024](adr/0024-integracao-em-duas-rodadas-e-desempate-pelo-arquivo.md)):
  a rodada 1 carrega a v1. A rodada 2 envia a v2, a v6 (a v1 chegando atrasada), a v7 (só
  cabeçalho) e a v5 (cópia da v2 com outro nome) **numa carga só**. O esperado é: retrato =
  v5, `arquivo_ignorado` = v2, v6 e v7, e histórico de 252 versões, 234 vigentes e 18
  fechadas. O desempate do retrato usa a modificação do arquivo na landing, então a ordem
  de envio vale. O workflow não tem mais o input `cenarios_de_falha`.
- **Testes por risco:** todo teste protege contra dado errado, vazamento de dado pessoal,
  custo, deploy quebrado ou falha de segurança. Forma e ordem de ADRs e do CHANGELOG não
  são testadas (só links quebrados). A matriz está em
  [`cenarios-reais.md`](cenarios-reais.md).
- **Cenários que viraram testes de unidade:** cp1252 (v8), full refresh, regra que para a
  carga (v4), queda de volume (v3) e coluna nova na origem. A integração não os roda mais;
  a matriz com o teste de cada um está em [`cenarios-reais.md`](cenarios-reais.md). As
  agendas v3, v4 e v8 continuam em `data/` para teste manual no dev.
- **Como forçar uma falha no dev** (para ver o e-mail com o motivo e o job vermelho): envie
  a v4 para a pasta da fonte na landing do dev e rode o job
  (`databricks bundle run essentials_carga_diaria -t dev`). A regra `data_plausivel` para a
  carga. O e-mail chega pela tarefa `avisar_falha`, e a `encerrar_com_falha` deixa o job
  vermelho. **Para voltar ao normal, envie a v5** (cópia da v2): ela tem a mesma data de
  referência e modificação mais recente que a v4, então vira o retrato. Só dados
  fictícios; o target `dev` nunca recebe dado real.
- **Sem UDF Python:** um teste de unidade recusa `udf`, `pandas_udf`, `LANGUAGE PYTHON` e
  `applyInPandas` em `src/`; a lógica é SQL e funções nativas.
- `DATABRICKS_HOST_DEV` (variável do repositório) é a URL do workspace de dev; o
  `databricks.yml` não traz o host.
- O Free Edition não oferece service principal com OIDC, por isso o CI de dev usa token.
- Quando houver produção, ative o deploy automático descomentando o `push` em `deploy.yml`.
- Nada é alterado à mão em produção: tudo passa pelo bundle.

## Cadeia de suprimentos

Detalhes e motivos em [ADR 0013](adr/0013-cadeia-de-suprimentos.md).

- **Actions fixadas pelo SHA do commit**, com a versão em comentário: uma tag pode ser
  movida para outro código, um SHA não.
- **Dependências com versão fixa** num único arquivo, `requirements-runtime.txt`, que o
  pipeline e o job instalam com `-r`; o `requirements-dev.txt` o inclui.
- **Dependabot** (`.github/dependabot.yml`) propõe toda semana as atualizações de actions
  e pacotes, só de versões publicadas há pelo menos 14 dias.
- **Permissões mínimas**: cada job do GitHub Actions declara só o que usa.

## pre-commit

As mesmas verificações do CI rodam na sua máquina antes de cada commit: ruff, YAML e
JSON válidos, fim de arquivo, espaços sobrando, chave privada e segredos (gitleaks).

```
pip install -r requirements-dev.txt
pre-commit install            # uma vez: ativa o hook de commit deste repositório
pre-commit run --all-files    # opcional: verifica tudo de uma vez
```

## Versões

O projeto usa versões semânticas, com uma tag por fase do plano de evolução
(`v0.1.0` = estado antes do plano). As mudanças de cada versão estão no
[`CHANGELOG.md`](../CHANGELOG.md).
