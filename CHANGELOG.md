# Changelog

Todas as mudanças relevantes do projeto ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto
usa [versionamento semântico](https://semver.org/lang/pt-BR/). Cada fase do
[plano de evolução](docs/plano-padrao-senior.md) sobe a versão menor; a `0.1.0` é o
estado antes do plano. Enquanto a versão for `0.x`, mudanças incompatíveis também sobem
só a versão menor.

## [Unreleased]

### Adicionado

- Fase 7, base de produção: ação `falhar` nas regras (exemplo `data_plausivel`); regras
  da chave geradas sozinhas; views `mon_volume`, `mon_estrutura`, `mon_execucoes` e
  `mon_custo_mensal`; tabela `mon_falhas` e tarefa `registrar_falha` com o motivo sem dado
  pessoal; alertas `falha_carga`, `qualidade_carga` e `custo_teto`; leitura de planilhas
  Excel; cenários de falha (agendas v3 e v4) na integração; ADRs 0014 e 0015.

- Campo `data_referencia` por fonte snapshot (`ingestao`, `conteudo` ou `nome_arquivo`): o
  retrato é o arquivo mais recente pela data de referência, não pela ordem de ingestão; a
  agenda usa `max(dt_entrevista)` (ADR 0016).
- Avisos `arquivo_ignorado` e `codificacao_invalida` em `mon_estrutura`, cobertos pelo
  alerta `qualidade_carga`.
- Agendas fictícias v5 (reenvio da v2), v6 (a v1 atrasada), v7 (só cabeçalho) e v8 (v2 em
  cp1252) e cenários de integração: v1, v2, v5, v6, v7, full refresh, v8, v3 e v4.
- `scripts/gerar_exclusao_titular.py`: gera o SQL de exclusão de um titular para revisão
  humana, sem executar nada e com o titular só como parâmetro (ADR 0017).
- `docs/padroes/retencao-e-exclusao.md` (política de retenção e exclusão de titular),
  `docs/cenarios-reais.md` (matriz de incidentes, defesas e testes) e ADRs 0016 e 0017.

### Alterado

- Testes enxugados por risco (327 para 272 e, com os novos, 336): cada teste protege contra
  dado errado, vazamento de dado pessoal, custo, deploy quebrado ou falha de segurança.
- `pipelines.reset.allowed = false` na bronze de arquivo, banco e API e no histórico SCD2:
  o full refresh não apaga o histórico nem reingere a landing. Mudar o schema da bronze
  passa a ser um procedimento manual, com decisão registrada.
- Roteiro de operação, `lgpd.md`, `camadas.md`, `arquitetura.md` e `desenvolvimento.md`
  com os avisos novos, a regra de testes por risco e os cenários de integração.
- Auto Loader em modo `rescue`; aviso de falha do job também para o suporte da Logos;
  landing de produção por variável (`landing_url`); painel Saúde da plataforma com taxa
  de sucesso, falhas, volume, estrutura e teto de custo; roteiro de operação com os novos
  avisos e o canal de envio de arquivos.
- Roteiro revisado a partir da Fase 7: o repositório passa a ser só o pacote Essentials,
  com a tabela de cobertura do pacote no plano e as Fases 7 (base de produção), 8
  (ambientes e esteira do cliente), 9 (template) e 10 (kit de serviço). Testes só no Free
  Edition; sem Terraform por enquanto.

### Removido

- Testes que conferiam a forma e a ordem dos ADRs e do CHANGELOG; ficou só a conferência de
  links relativos quebrados.

### Corrigido

- Uma planilha antiga reenviada depois, ou um arquivo só com cabeçalho, não substitui mais
  o retrato do snapshot.

### Segurança

- Exclusão de titular com procedimento documentado: SQL gerado para revisão, com guarda
  contra parâmetro vazio e comparação por campo inteiro, `REORG ... APPLY (PURGE)` e
  `VACUUM`.
- Os avisos de arquivo mostram só o nome do arquivo; o nome nunca pode ter dado pessoal.
- A `expressao` de `data_referencia` é código executável e deve ser revisada no PR.
- Pendência: as fontes `incremental` e `cdc` leem a bronze em streaming sem
  `skipChangeCommits`; a exclusão de titular ainda quebraria a carga delas (ADR 0017).

## [0.7.0] - 2026-11-03

Fase 6: documentação de engenharia.

### Adicionado

- ADRs das decisões tomadas antes do plano e nas Fases 1 e 2: 0006 sem dbt, 0007
  acelerador orientado por metadados, 0008 snapshot com AUTO CDC e SCD tipo 2, 0009
  expectations em tabela intermediária, 0010 Free Edition só com dados fictícios, 0011
  deploy de produção por OIDC, 0012 guardrails do Claude Code e 0013 cadeia de
  suprimentos; índice em `docs/adr/README.md`.
- Diagramas Mermaid: fluxo dos dados e ambientes com CI/CD no README, fluxo dos dados e
  da carga diária em `docs/arquitetura.md` e fluxo dos agentes em `docs/desenvolvimento.md`.
- `docs/arquitetura.md`, `docs/guia-free-edition.md`, `docs/levando-ao-azure.md` e
  `docs/desenvolvimento.md`, com o conteúdo detalhado que saiu do README.
- Este CHANGELOG e as tags `v0.1.0` a `v0.7.0`.
- Testes da documentação: ADRs em sequência e no formato, índice completo, CHANGELOG em
  ordem e com links, e nenhum link relativo quebrado no README e em `docs/`.

### Alterado

- README reorganizado: visão de 1 minuto no topo, como rodar, como adaptar a um cliente e
  mapa da documentação; os detalhes remetem a `docs/`.
- Skills, agente documentador e template de PR apontam para os novos documentos e para o
  CHANGELOG.

## [0.6.0] - 2026-11-03

Fase 5: testes de integração e de dados (ADR 0005).

### Adicionado

- Target `ci` no bundle (projeto `<projeto>_ci`, estado de deploy próprio).
- Workflow `integracao.yml`, manual e às 1h de segunda a sexta, nunca em PR: implanta o
  `ci`, carrega a agenda fictícia v1 e a v2, confere os dados e destrói tudo no fim.
- Asserções em `tests/integracao/` pelo `databricks-sdk`, com os totais esperados da
  semente fixa; `scripts/integracao.py`, que só mexe em schemas `_ci`.
- Marcadores `unidade` e `integracao` do pytest; `pytest -q` roda só unidade.

### Alterado

- `prevent_destroy` saiu de `resources/governanca.yml` e passou a ser declarado nos
  targets `dev` e `prod`.
- Agendamento do job pausado em dev.

## [0.5.0] - 2026-11-03

Fase 4: observabilidade e custos (ADRs 0003 e 0004).

### Adicionado

- Event log do pipeline publicado em `mon_log_eventos`.
- Views `mon_qualidade_diaria`, `mon_atualizacao` e `mon_custo_diario`, criadas pela
  tarefa `governanca_depois`.
- Alerta SQL de atraso da carga, regra `health` de duração com aviso por e-mail e painel
  "Saúde da plataforma".
- Tags `projeto`, `cliente` e `ambiente` em todos os recursos; relatório mensal de custo
  no roteiro de operação.

### Alterado

- Ingestões de banco e API só rodam quando o `fontes.yml` tem fonte do tipo
  (`condition_task`).

## [0.4.0] - 2026-11-03

Fase 3: governança no Unity Catalog como código (ADRs 0001 e 0002).

### Adicionado

- Schemas, volume e permissões no bundle (`resources/governanca.yml`), com grupos como
  variáveis.
- Gold em schema próprio, `<projeto>_gold`, o único lido pelo negócio.
- Máscara de coluna nos dados pessoais da gold e tag `pii`, a partir de `sensivel: true`
  no `fontes.yml`.

### Alterado

- `setup/00_setup_free_edition.sql` reduzido ao catálogo e à origem simulada.
- Em dev, os schemas passam a ter o prefixo `dev_<usuário>_`; o schema antigo
  `essentials.portfolio` foi apagado.

## [0.3.0] - 2026-11-03

Fase 2: segurança e cadeia de suprimentos (ADR 0013).

### Adicionado

- Dependabot para actions e pip, com cooldown de 14 dias.
- Varredura de segredos com gitleaks no CI (job `segredos`) e no pre-commit.
- `LICENSE`, `SECURITY.md`, `CODEOWNERS`, template de PR e templates de issue.

### Alterado

- Actions fixadas pelo SHA do commit.
- Dependências do pipeline e do job com versão fixa em `requirements-runtime.txt`.
- Permissões mínimas em cada workflow e em cada job.

## [0.2.0] - 2026-11-03

Fase 1: camada de IA do projeto (ADR 0012).

### Adicionado

- Permissões versionadas do Claude Code (`.claude/settings.json`).
- Hooks em Python, com testes: proteção de comandos e arquivos, lint após edição e
  restrição de edição dos subagentes.
- `scripts/perfilar_dados.py`: perfil de um arquivo sem expor dados pessoais.
- Seis subagentes, seis skills novas (oito no total) e evals das skills críticas.

### Alterado

- `CLAUDE.md` enxuto, com os padrões detalhados em `docs/padroes/`.

## [0.1.0] - 2026-11-03

Estado antes do plano de evolução.

### Adicionado

- Acelerador Essentials: lakehouse medalhão orientado por metadados, com bronze e silver
  genéricas a partir do `config/fontes.yml`, AUTO CDC com SCD tipo 2 e gold em modelo
  estrela.
- Padrão de nomes `camada_tipo_nome` e prefixos de coluna, validados pelos testes.
- Gerador de agendas fictícias e setup do Free Edition.
- CI com lint, testes e `bundle validate`; deploy de produção por OIDC.
- Painel AI/BI de entrevistas no bundle.
- Dicionário de dados da silver e da gold no Unity Catalog.
- Plano de evolução para o padrão sênior.

[Unreleased]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/releases/tag/v0.1.0
