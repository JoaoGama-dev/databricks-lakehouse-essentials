# Plano de evolução para o padrão sênior — essentials_portfolio

Documento de execução para o Claude Code. Ele leva o projeto do estado atual (que já é
bom) ao padrão de um time sênior de engenharia de dados e de engenharia de IA: segurança
por padrão, guardrails determinísticos, governança como código, observabilidade, testes
de integração e uso disciplinado de agentes.

---

## Como usar este documento

**Para o João (humano):**

1. Salve este arquivo em `docs/plano-padrao-senior.md`.
2. Execute **uma fase por vez**, cada uma numa branch e num pull request próprios.
3. No Claude Code, em **modo Plan**, use o prompt:
   > Leia @docs/plano-padrao-senior.md e @CLAUDE.md. Planeje só a Fase N. Me mostre o
   > plano, os arquivos que vai criar ou alterar e os critérios de aceite. Espere meu OK.
4. Itens marcados **[AÇÃO HUMANA]** são feitos por você no navegador (GitHub,
   Databricks). O Claude não tem acesso a essas telas e não deve tentar contornar isso.
5. Ao fim de cada fase: CI verde, revisão do diff, merge. Só então a próxima.

**Para o Claude Code (executor):**

- Siga o `CLAUDE.md` em tudo. Onde este plano e o `CLAUDE.md` divergirem, pergunte.
- **Não invente sintaxe.** Antes de escrever configuração do bundle, confirme o formato
  com `databricks bundle schema` ou com a documentação oficial da Databricks. Antes de
  escrever configuração do Claude Code (settings, hooks, agentes, skills), confirme na
  documentação oficial do Claude Code. Se não conseguir confirmar, diga isso no plano.
- Mudanças pequenas e revisáveis: um PR por fase, commits por item.
- Nunca leia, copie ou exiba dados reais de clientes. Só os dados fictícios do gerador.
- Ambiente do João: **Windows**, com a ferramenta **PowerShell** no Claude Code. Tudo
  que for script (hooks, utilitários) deve ser em **Python** e funcionar em Windows e
  Linux (o CI roda em Linux).
- Ao terminar cada item, rode `ruff check .` e `pytest -q` e mostre o resultado.

---

## Diagnóstico do estado atual

**Pontos fortes (manter):**

- Acelerador orientado por metadados: bronze e silver genéricas a partir de
  `config/fontes.yml`, validado por JSON Schema.
- Lógica da configuração isolada em `src/essentials/config_fontes.py`, sem Spark, com
  63 testes passando e lint limpo.
- Padrão de nomes (`camada_tipo_nome`, prefixos de coluna), dicionário de dados
  obrigatório e gold em modelo estrela.
- AUTO CDC com SCD tipo 2, expectations numa tabela intermediária (não em view).
- LGPD: dados reais fora do Git, Free Edition só com dados fictícios, telefone mascarado.
- CI com lint, testes e `bundle validate`; deploy de produção por OIDC com aprovação;
  host fora do repositório; 4 PRs mergeados com CI verde; painel AI/BI no bundle.

**Lacunas para o padrão sênior:**

| Área | Lacuna |
| --- | --- |
| IA no desenvolvimento | sem `.claude/settings.json` versionado, sem hooks, sem subagentes; só 2 skills; regras críticas existem só como texto no `CLAUDE.md` |
| LGPD no uso de IA | a skill `novo-cliente` manda ler linhas do CSV do cliente, o que coloca dados pessoais no contexto do modelo |
| Cadeia de suprimentos | actions fixadas por tag, não por SHA; dependências do pipeline e do job sem versão; sem Dependabot; sem varredura de segredos |
| Governança | schema, volume e permissões criados à mão (`setup/*.sql`); sem grants como código; bronze com dado pessoal bruto sem restrição explícita |
| Observabilidade | event log do pipeline não publicado; sem histórico de qualidade; sem alerta de atraso da carga; sem acompanhamento de custo |
| Testes | só testes estáticos; nenhum teste de integração que rode o pipeline e confira os dados |
| Custo | tarefas de ingestão de banco e API rodam todo dia mesmo sem fontes desses tipos |
| Documentação de engenharia | sem ADRs, sem diagrama de arquitetura renderizável, sem CHANGELOG, sem templates de PR e issue, sem arquivo `LICENSE` |
| Fábrica de projetos | criar um cliente novo ainda é copiar e editar o repositório, em vez de gerar a partir de um template |

---

## Fase 1 — Camada de IA do projeto (Claude Code)

Objetivo: transformar as regras críticas em **guardrails determinísticos** (permissões
e hooks), deixar o `CLAUDE.md` enxuto e criar a equipe de agentes e skills.

Princípio: **o que não pode falhar vira permissão ou hook; o que é orientação fica no
`CLAUDE.md` ou numa skill.** Texto no `CLAUDE.md` é uma instrução que o modelo pode
esquecer; um hook sempre roda.

### 1.1 Permissões versionadas — `.claude/settings.json`

Crie o arquivo (versionado; o `settings.local.json` continua ignorado). Regras para os
dois shells, `Bash(...)` e `PowerShell(...)`:

- **allow** (rodam sem perguntar, só leitura ou validação):
  `ruff check *`, `pytest *`, `python -m pytest *`, `databricks bundle validate *`,
  `git status`, `git diff *`, `git log *`, `python data/gerar_dados_exemplo.py *`,
  `python scripts/perfilar_dados.py *`.
- **ask** (sempre pedem confirmação):
  `databricks bundle deploy *`, `databricks bundle run *`, `databricks fs cp *`,
  `git commit *`, `git push *`.
- **deny** (nunca):
  `databricks bundle deploy -t prod*`, `databricks bundle deploy --target prod*`,
  `databricks bundle destroy *`, `git push --force*`, `git push -f*`,
  `Read(./.env)`, `Read(./.env.*)`, `Read(./data/privado/**)`,
  `Read(./data/tabela_*)`, `Read(./.databricks/**)`.

Avalie também a seção `sandbox` (confirme o suporte no Windows antes de ativar).

### 1.2 Hooks — `.claude/hooks/` + registro no `settings.json`

Scripts em Python, sem dependências externas, lendo o JSON da entrada padrão.

1. **`proteger_comandos.py`** — evento `PreToolUse`, matcher `Bash|PowerShell`.
   Bloqueia (saída 2, motivo em português no stderr):
   - deploy, destroy ou run com target `prod`;
   - `git push` forçado e push direto na `main`;
   - comandos que leiam arquivos em `data/privado/` ou CSVs reais de `data/`
     (qualquer `data/*.csv` que não seja `data/agenda_exemplo_v*.csv`);
   - `databricks auth token` e comandos que imprimam tokens;
   - remoção recursiva (`rm -rf`, `Remove-Item -Recurse`) fora de `.venv`, caches e
     `.databricks/`.
2. **`proteger_arquivos.py`** — evento `PreToolUse`, matcher `Read|Edit|Write`.
   Bloqueia leitura de dados reais (mesma regra acima) e de `.env*`; bloqueia edição de
   `.github/workflows/deploy.yml` sem que o pedido do usuário cite esse arquivo (na
   dúvida, devolva motivo pedindo confirmação explícita).
3. **`lint_apos_edicao.py`** — evento `PostToolUse`, matcher `Edit|Write`. Se o arquivo
   editado for `.py`, roda o ruff do `.venv` (procure `.venv/Scripts/ruff.exe` e
   `.venv/bin/ruff`; se não achar, termine sem erro) só nesse arquivo e devolve os
   problemas ao Claude (saída 2, que no `PostToolUse` só avisa).

Comando de cada hook: `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/<script>.py"`.
Confirme que a expansão de `${CLAUDE_PROJECT_DIR}` funciona no Windows.

**Testes obrigatórios:** `tests/test_hooks.py` alimenta cada script com JSONs de exemplo
(comando permitido, comando bloqueado, caminho real, caminho fictício) e confere o código
de saída. Hook sem teste não entra.

### 1.3 Perfilamento de dados sem expor dados pessoais

Problema: para adaptar o projeto a um cliente, o modelo precisa entender a estrutura dos
dados, mas não precisa ver nomes, telefones ou documentos.

Crie `scripts/perfilar_dados.py`, que recebe um arquivo (CSV, XLSX opcional via
biblioteca já instalada, ou texto) e imprime **só metadados**:

- codificação, separador, BOM, quebra de linha, número de linhas;
- linhas com padrão estrutural (separadores, totais, cabeçalhos repetidos), descritas por
  padrão e não por conteúdo;
- por coluna: nome, tipo inferido, % de nulos, nº de distintos, tamanho mín/máx,
  **padrões de formato** (ex.: `99/99/9999`, `(99) 99999-9999`, `Aa aaaa`), e
  **valores mais frequentes somente** para colunas de baixa cardinalidade (até 30
  distintos), que é onde aparecem status e categorias;
- **detecção de dados pessoais** por padrão (CPF, CNPJ, telefone, e-mail, nome próprio
  provável), marcando a coluna como sensível e sugerindo `mascarar`.

Nenhum valor de coluna sensível ou de alta cardinalidade sai na tela. Teste com os dados
fictícios do gerador.

Depois, atualize as skills `novo-cliente` e `nova-fonte`: os dados reais do cliente ficam
em `data/privado/` (ignorado pelo Git e bloqueado pelos hooks) e a análise é feita
**exclusivamente** pela saída do `perfilar_dados.py`.

### 1.4 `CLAUDE.md` enxuto e padrões em arquivos próprios

O `CLAUDE.md` é carregado em toda conversa e consome contexto. Deixe nele só o essencial
(meta: até ~100 linhas): o que é o projeto, comandos, regras inegociáveis e onde está cada
coisa. Mova os detalhes para `docs/padroes/`, referenciados pelo `CLAUDE.md`:

- `docs/padroes/nomes.md` — tabelas, colunas e prefixos;
- `docs/padroes/camadas.md` — regras de bronze, silver, gold, AUTO CDC e expectations;
- `docs/padroes/lgpd.md` — dados reais, mascaramento, perfilamento, o que o modelo pode ver;
- `docs/padroes/fluxo-de-trabalho.md` — branch, PR, comandos de validação, fases.

Atualize também a seção "Antes de propor uma mudança": com as permissões da 1.1, o
Claude **roda** `ruff check .`, `pytest -q` e `databricks bundle validate -t dev` e mostra
o resultado, em vez de só listar os comandos.

### 1.5 Subagentes — `.claude/agents/`

Cada um com `name`, `description` (dizendo quando usar), `tools` mínimas, `model` e
`skills` pré-carregadas. Todos respondem em português e seguem o `CLAUDE.md`.

| Agente | Responsabilidade | Ferramentas | Modelo sugerido | Skills |
| --- | --- | --- | --- | --- |
| `arquiteto-dados` | analisa fontes pelo perfilamento, propõe `fontes.yml`, regras, modelo estrela e indicadores; termina sempre pedindo aprovação | leitura + rodar `perfilar_dados.py` | o mais capaz disponível (opus) | novo-cliente, adr |
| `engenheiro-dados` | implementa config, SQL, Python e testes conforme o plano aprovado | leitura, edição, ruff, pytest | inherit | nova-fonte, novo-indicador |
| `qa-dados` | roda lint, testes e `bundle validate`; revisa expectations, dicionário de dados, nomes e cobertura de testes; pode editar só `tests/` | leitura, edição em `tests/`, comandos de teste | sonnet | revisao-qualidade |
| `devops-dados` | deploy e execução **só em dev**, leitura do resultado e do event log | comandos do Databricks (os de prod já estão bloqueados) | sonnet | implantar-dev |
| `revisor-seguranca` | revisa o diff atrás de segredos, dados pessoais, permissões amplas, dependências sem versão | só leitura | sonnet | revisar-pr |
| `documentador` | README, roteiro de operação, dicionário, CHANGELOG, ADRs | leitura, edição em `docs/` e `*.md` | sonnet | entrega, adr |

Fluxo padrão de uma mudança grande:
`arquiteto-dados` → **aprovação do João** → `engenheiro-dados` → `qa-dados`
(volta ao engenheiro se falhar) → `revisor-seguranca` → `devops-dados` (dev) →
`documentador` → pull request → CI → **aprovação do João** → merge.
Produção só pelo workflow de deploy, nunca por agente.

Documente esse fluxo numa seção curta do `CLAUDE.md`.

### 1.6 Skills novas — `.claude/skills/`

Mantenha `novo-cliente` e `nova-fonte` (atualizadas na 1.3) e crie:

- `novo-indicador` — KPI novo na gold: modelagem (dim/fato/agg), colunas com tipo e
  COMMENT, teste, dicionário e, se fizer sentido, metric view.
- `revisao-qualidade` — checklist do `qa-dados`: lint, testes, nomes, dicionário,
  expectations para toda chave, nenhum `WHERE` escondendo qualidade.
- `implantar-dev` — validate, deploy e run em dev com os dados fictícios; como ler o
  resultado, a aba Data quality e o event log; o que fazer em cada tipo de erro.
- `revisar-pr` — checklist de segurança e qualidade de um diff, com saída em formato
  fixo (bloqueante / recomendado / ok).
- `adr` — registra uma decisão de arquitetura em `docs/adr/NNNN-titulo.md`
  (contexto, decisão, alternativas, consequências).
- `entrega` — checklist de entrega ao cliente: roteiro de operação com os nomes reais
  do projeto, checklist de acessos, dicionário, treinamento, aceite.

Toda skill: `description` clara de quando usar, passos numerados, critério de pronto e,
quando gerar arquivo, o formato esperado.

### 1.7 Evals das skills

Skill também precisa de teste. Crie `tests/evals/` com um caso por skill crítica
(`novo-cliente`, `nova-fonte`): a entrada (perfil de dados fictício) e uma lista de
verificações sobre o resultado esperado (ex.: "toda coluna com telefone tem `mascarar`",
"toda coluna da chave tem regra `nao_nulo` com `drop`", "nomes seguem os prefixos").
Documente em `tests/evals/README.md` como rodar a avaliação manualmente com o Claude Code
e conferir a lista. Não é para o CI chamar o modelo.

**Critérios de aceite da Fase 1:** settings e hooks ativos e testados; perfilamento sem
vazar valores sensíveis (com teste); `CLAUDE.md` enxuto apontando para `docs/padroes/`;
6 subagentes e 8 skills; ruff e pytest verdes.

**Status: concluída (branch `fase-1`).** Ajustes feitos ao confirmar a documentação
oficial do Claude Code:

- O hook `PreToolUse` não recebe o texto do pedido do usuário; a proteção do
  `deploy.yml` virou a regra `ask` `Edit(./.github/workflows/deploy.yml)`.
- Subagentes não restringem ferramentas por pasta; `qa-dados` e `documentador` usam o
  hook `restringir_edicao.py` no próprio frontmatter.
- O sandbox não roda no Windows nativo; não foi ativado (registrado em
  `docs/padroes/fluxo-de-trabalho.md`).
- O perfilamento não lê Excel (nenhuma biblioteca instalada): orienta salvar como CSV.
- O hook de comandos bloqueia qualquer menção a planilhas reais, inclusive em mensagens
  de commit; para citar caminhos de dados, use `git commit -F`.

---

## Fase 2 — Segurança e cadeia de suprimentos

1. **Actions fixadas por SHA**, com a versão num comentário
   (`uses: actions/checkout@<sha> # v7.0.1`), nos dois workflows.
2. **Dependabot** (`.github/dependabot.yml`) para `github-actions` e `pip`, semanal,
   agrupando atualizações menores.
3. **Versões fixas** das dependências do pipeline e do job (`pyyaml`, `jsonschema`,
   `requests`), num único lugar (variáveis do bundle ou um arquivo de requisitos
   referenciado), iguais às do `requirements-dev.txt`.
4. **Varredura de segredos no CI**: job com gitleaks (versão fixada por SHA) em todo PR.
5. **pre-commit** (`.pre-commit-config.yaml`): ruff, check-yaml, check-json,
   end-of-file-fixer, trailing-whitespace, detect-private-key e gitleaks. Explique no
   README como instalar (`pre-commit install`).
6. **Arquivos do repositório**: `LICENSE` com o texto de direitos reservados que já está
   no README, `SECURITY.md` (como reportar uma vulnerabilidade), `.github/CODEOWNERS`,
   `.github/pull_request_template.md` (checklist: testes, dicionário, LGPD, ADR quando
   houver decisão), templates de issue (bug, nova fonte, novo indicador).
7. **Permissões mínimas** em cada workflow e em cada job (`permissions:` explícito).
8. **[AÇÃO HUMANA]** No GitHub: ativar *Secret scanning* e *Push protection*,
   *Dependabot alerts* e conferir a proteção da `main` (PR obrigatório, CI obrigatório,
   sem push forçado, revisão obrigatória quando houver colaboradores).

**Aceite:** CI com 3 jobs verdes (testes, validar_bundle, segredos); nenhuma action por
tag; nenhuma dependência sem versão.

**Status: concluída (branch `fase-2`).** Decisões tomadas na execução:

- Versões num único arquivo, `requirements-runtime.txt`, instalado pelo pipeline e pelo
  job com `-r` (cada dependência do bundle é uma linha de requisitos do pip), em vez de
  variáveis do bundle: assim o Dependabot também o atualiza. Validado com o job rodando
  em dev.
- gitleaks no CI pelo binário oficial conferido pelo SHA-256 da release, em vez da
  action: sem Node, sem licença para organizações e a mesma versão do pre-commit.
- Dependabot com `cooldown` de 14 dias, a regra das 2 semanas aplicada automaticamente.
- O histórico completo do repositório foi varrido pelo gitleaks antes do PR: nada
  encontrado.

---

## Fase 3 — Governança no Unity Catalog como código

1. **Schema e volume no bundle**: declare `resources.schemas` e `resources.volumes` (o
   schema do projeto e o volume `landing`), com `grants`. Confirme a sintaxe com
   `databricks bundle schema`. O `setup/00_setup_free_edition.sql` fica só com o que
   simula sistemas de origem (`<projeto>_origem`).
2. **Modelo de acesso por grupos** (variáveis do bundle, para trocar por cliente):
   - `grupo_engenharia` — tudo no schema do projeto;
   - `grupo_leitura_gold` — `SELECT` só nas tabelas `gold_*` (via views ou grants por
     tabela; documente a escolha num ADR);
   - bronze e `silver_int_*` sem acesso para usuários de negócio.
   No Free Edition, use o seu usuário e documente como fica no cliente.
3. **Dados pessoais**: avalie, num ADR, trocar ou complementar o mascaramento na silver
   por **column masks** do Unity Catalog nas colunas sensíveis da silver e da gold
   (quem é da engenharia vê o dado, o resto vê mascarado). Implemente se for suportado
   no ambiente; no Free Edition, registre a limitação.
4. **Tags de governança**: marque as colunas com dado pessoal (ex.: tag `pii`), a partir
   de uma flag `sensivel: true` no `fontes.yml` (atualize o schema JSON e os testes).

**Aceite:** `setup` reduzido; permissões declaradas no bundle; ADR do modelo de acesso.

**Status: concluída (branch `fase-3`).** Decisões tomadas na execução (ADRs 0001 e 0002):

- A gold foi para um schema próprio, `<projeto>_gold`: o grupo de leitura recebe
  `USE SCHEMA` e `SELECT` só nele, sem grants por tabela nem views. A bronze, a silver e
  a landing ficam no schema do projeto, só da engenharia.
- Schemas e volume com `prevent_destroy`. Em dev o bundle prefixa os schemas com
  `dev_<usuário>_`; os dados foram reconstruídos no schema novo com as mesmas contagens.
- A landing é volume nos dois ambientes; em prod, volume externo sobre a external
  location do cliente.
- `ALTER ... SET MASK` é recusado em tabelas do pipeline: as máscaras são declaradas na
  própria gold (`MASK` na lista de colunas), com a função criada pela tarefa
  `governanca_antes` do job. O mascaramento fixo da silver continua.
- As tags `pii` são aplicadas pela tarefa `governanca_depois`, pulando as tabelas
  internas `__materialization_*`.
- No Free Edition só há um usuário: os três grupos são o próprio usuário (leitura é
  `account users`) e não dá para ver a máscara do lado de quem não tem acesso; ficou
  conferido que a máscara está registrada. Validar no cliente com um usuário sem acesso.

---

## Fase 4 — Observabilidade e custos

1. **Event log publicado** em tabela do Unity Catalog pela configuração `event_log` do
   pipeline (catálogo, schema e nome; confirme a sintaxe YAML do bundle).
2. **Monitoramento de qualidade**: crie `src/pipeline/monitoramento.sql` (ou um job SQL,
   se ler o event log dentro do próprio pipeline não for recomendado — verifique e
   decida num ADR) com uma tabela ou view `mon_qualidade_diaria`: por dia, tabela e
   regra, quantas linhas passaram, foram descartadas ou geraram alerta.
3. **Atraso da carga**: view `mon_atualizacao` com o último `_ingerido_em` de cada
   silver e um alerta SQL (ou tarefa de verificação no job) quando passar de 26 horas.
4. **Saúde do job**: regra de duração (`health`) com aviso por e-mail quando a carga
   demorar mais que o normal, e notificação de falha já existente.
5. **Custos**: consulta documentada em `docs/roteiro-de-operacao.md` sobre as tabelas de
   sistema de faturamento, filtrando pelos recursos do projeto, para o relatório mensal.
   Marque todos os recursos com tags (`projeto`, `cliente`, `ambiente`) no bundle para
   o custo poder ser separado.
6. **Tarefas de ingestão só quando há fonte**: nenhuma tarefa serverless deve rodar se
   não houver fonte `banco` ou `api` no `fontes.yml`. Proponha a solução (tarefa de
   condição, arquivo de recurso opcional ou outra) e registre num ADR.
7. **Página "Saúde da plataforma"** no painel AI/BI, lendo as tabelas `mon_*`.

**Aceite:** event log consultável; histórico de qualidade; alerta de atraso; custo por
projeto identificável; nenhuma tarefa ociosa diária.

**Status: concluída (branch `fase-4`).** Decisões tomadas na execução (ADRs 0003 e 0004;
os ADRs da Fase 6 passam a ser numerados a partir de 0006, depois do 0005 da Fase 5):

- As views `mon_*` ficam fora do pipeline, criadas pela tarefa `governanca_depois`: na
  primeira atualização o event log ainda não existe. A ação de cada regra vem do
  `fontes.yml`, porque o event log só traz aprovadas e reprovadas.
- O atraso é medido pela última atualização concluída do pipeline; o `_ingerido_em` só
  muda com arquivo novo e daria alarme falso.
- Alert v2 só notifica usuários do workspace (ou destinos de notificação): variável
  `usuario_alerta`, separada do `alert_email` do job.
- Custo filtrado pelos IDs do job e do pipeline: no Free Edition as tags chegam ao
  faturamento do job, mas não ao do pipeline serverless; no cliente, tags garantidas por
  política de uso serverless.
- Painel "Saúde da plataforma" separado, sobre o schema do projeto (ADR 0001).
- Ingestões com `condition_task` e `run_if: NONE_FAILED`; um teste mantém as variáveis
  coerentes com o `fontes.yml`.
- Limite de duração em 900 s: as execuções de dev levam de 2,4 a 5,3 min.

---

## Fase 5 — Testes de integração e de dados

1. **Workflow `integracao.yml`** (manual e agendado à noite, nunca em PR de fork):
   - `databricks bundle deploy -t dev`;
   - `databricks bundle run <pipeline> --validate-only` (valida o grafo sem processar);
   - limpa a landing de teste, envia `agenda_exemplo_v1.csv`, roda a carga;
   - confere os dados; envia a v2, roda de novo e confere o histórico.
2. **Asserções de dados** em `tests/integracao/`, rodando SQL pelo `databricks-sdk`
   (versão fixada): como o gerador usa semente fixa, os totais esperados são
   determinísticos. Confira, no mínimo: linhas na silver, descartes por regra, nenhuma
   chave nula, quantidade de versões no histórico após a v2, e que a soma da agregada
   bate com a fato.
3. Use um **schema de teste isolado** (variável `projeto` com sufixo `_ci`) para não
   misturar com o seu ambiente de dev; ao fim, limpe o que foi criado.
4. Separe os testes com marcadores do pytest (`unidade` e `integracao`); o CI de PR roda
   só `unidade`.
5. **Opcional, se o custo de tempo valer:** testes locais com PySpark para
   `expressoes_silver` e `expressao_limpeza`, executando as expressões geradas sobre
   linhas de exemplo.

**Aceite:** o workflow de integração passa de ponta a ponta com os dados fictícios.

**Status: concluída (branch `fase-5`).** Decisões tomadas na execução (ADR 0005):

- Target `ci` próprio (projeto `<projeto>_ci`, estado de deploy separado), em vez de
  `-t dev` com outra variável, que recriaria os recursos do dev.
- A origem simulada do `ci` é criada pelo próprio `setup/00_setup_free_edition.sql`;
  `scripts/integracao.py` só aceita schemas terminados em `_ci`, `_ci_gold` e `_ci_origem`.
- Ordem: `governanca_antes` antes do `--validate-only` (a gold usa a função de máscara).
  O workflow começa e termina apagando o `ci`, para a v1 nunca ser lida sobre sobras.
- `prevent_destroy` saiu da base e fica nos targets `dev` e `prod`: a CLI antes da
  v1.22.0 ignora override para `false`, e o destroy do CI foi recusado na 1ª execução.
- Totais esperados (semente fixa): v1 229 no retrato e 227 na silver; v2 236, 234, 252
  no histórico e 18 fechadas; 2 descartes em `nome_preenchido`.
- Workflow à 1h de segunda a sexta e manual, nunca em PR; validado na branch com um
  gatilho `push` temporário, removido antes do merge. Agendamento do job pausado em dev.
- Sem testes locais com PySpark (item opcional): Java e ~300 MB no Windows; a integração
  já executa as expressões no Databricks.
- O Free Edition recusa novas execuções de job depois de muito uso no dia ("Triggering
  new runs ... is currently disabled temporarily"); o workflow falha nesse caso.

---

## Fase 6 — Documentação de engenharia

1. **ADRs** em `docs/adr/`, começando pelas decisões já tomadas:
   0001 sem dbt (pipelines declarativos), 0002 acelerador orientado por metadados,
   0003 snapshot com AUTO CDC e SCD tipo 2, 0004 expectations em tabela intermediária,
   0005 Free Edition só com dados fictícios, 0006 deploy de produção por OIDC.
2. **Diagrama de arquitetura em Mermaid** no README (fontes → landing → bronze → silver
   → gold → painel, com CI/CD e ambientes), e um diagrama do fluxo dos agentes da Fase 1.
3. **CHANGELOG.md** (formato Keep a Changelog) e versões semânticas com tags
   (`v0.1.0` = estado atual; cada fase sobe a versão menor).
4. README reorganizado: visão de 1 minuto no topo, depois "como rodar", e os detalhes
   remetendo a `docs/`.

**Status: concluída (branch `fase-6`).** Decisões tomadas na execução:

- ADRs retroativos numerados de 0006 a 0011 (0001 a 0005 já eram das Fases 3 a 5), com
  a data da decisão e a do registro, e mais dois para as Fases 1 e 2: 0012 guardrails do
  Claude Code e 0013 cadeia de suprimentos. Índice em `docs/adr/README.md`.
- Tags retroativas nos merges de cada fase: `v0.1.0` (plano, PR #5), `v0.2.0` (#6),
  `v0.3.0` (#7), `v0.4.0` (#10), `v0.5.0` (#11), `v0.6.0` (#12) e `v0.7.0` no merge desta
  fase.
- README de 492 para cerca de 140 linhas; o conteúdo detalhado foi para
  `docs/arquitetura.md`, `docs/guia-free-edition.md`, `docs/levando-ao-azure.md` e
  `docs/desenvolvimento.md`, sem perda. O diagrama dos agentes fica em
  `docs/desenvolvimento.md`, com link no README.
- Mermaid só com `flowchart` e `#60;`/`#62;` no lugar de `< >`; sem Node na máquina, a
  renderização é conferida no GitHub. Um teste barra link relativo quebrado no README e
  em `docs/`.
- A direção futura do módulo de IA Enterprise ficou nos próximos passos do README.

---

## Fase 7 — A fábrica: template de bundle

Objetivo: criar um projeto de cliente novo com um comando, em vez de copiar o repositório.

1. Transforme o acelerador num **template de bundle da Databricks** (pasta `template/`
   com o schema de perguntas e os arquivos parametrizados), para usar com
   `databricks bundle init <caminho ou URL do repositório>`. Perguntas mínimas: nome do
   projeto, catálogo, e-mail de alerta, se terá painel, tipos de fonte esperados.
   Confirme o formato de template na documentação oficial.
2. O projeto gerado já sai com: `fontes.yml` vazio comentado, CI/CD, `.claude/`
   completo (settings, hooks, agentes, skills), `docs/padroes/`, ADRs base e roteiro de
   operação com marcadores para os nomes do cliente.
3. Teste no CI: gerar um projeto a partir do template numa pasta temporária e rodar
   `ruff`, `pytest` e `bundle validate` nele.
4. **[AÇÃO HUMANA]** Marcar o repositório como *Template repository* no GitHub, se
   preferir também esse caminho.

**Aceite:** um projeto novo gerado pelo template passa no CI sem edição manual.

---

## Fora do escopo agora — módulo de IA (pacote Enterprise)

Não implementar no Essentials. Registrar só como direção futura no README:
RAG sobre documentos do cliente (Vector Search sobre uma tabela de trechos gerada por
pipeline), agente de perguntas sobre a gold (Genie e ferramentas no Unity Catalog),
avaliação de qualidade das respostas e rastreamento (MLflow). Quando chegar a hora, será
um projeto separado, com seu próprio plano.

---

## Apêndice A — Conceitos de LLM aplicados a este projeto

Cada peça resolve um problema criado pela anterior:

| Conceito | Problema que resolve | Onde aparece para você |
| --- | --- | --- |
| Janela de contexto | o modelo só "vê" uma quantidade limitada de texto por vez | `CLAUDE.md` enxuto, `/clear` entre tarefas, subagentes com contexto próprio |
| RAG | o modelo não conhece os documentos da empresa e não cabem todos no contexto | produto futuro (Enterprise); no seu dia a dia, o Claude Code lê os arquivos direto |
| Embeddings | para buscar por significado, o texto vira vetor | parte do RAG |
| Banco vetorial | guardar e buscar vetores rápido | Vector Search da Databricks, no RAG futuro |
| Tool calling | o modelo só gera texto; para agir, chama ferramentas | o Claude Code lendo arquivos e rodando `ruff`, `pytest`, `databricks` |
| Agente | uma chamada de ferramenta não basta; é preciso planejar, agir e verificar em ciclo | Claude Code e os subagentes da Fase 1; Genie |
| Structured output | texto livre é difícil de usar por programa | skills com formato de saída fixo (ex.: `revisar-pr`), YAML validado por schema |
| Streaming | esperar a resposta inteira é lento | resposta aparecendo aos poucos no painel do Claude Code |
| Guardrails | agente com ferramentas pode fazer estrago | permissões, hooks, deny de produção e de dados reais |
| Prompt caching | reenviar o mesmo contexto toda vez é caro e lento | automático no Claude Code; `CLAUDE.md` estável ajuda |
| Fallback | modelo ou serviço indisponível | em produção: modelo alternativo; no seu fluxo: CI e testes não dependem do modelo |
| Evals | sem medir, não se sabe se a IA acerta | `tests/evals/` das skills; os testes do pipeline são o "eval" do código |
| Observabilidade | o que acontece em produção fica invisível | event log, `mon_*`, alertas; no Claude Code, o histórico de sessões e o uso |

## Apêndice B — Boas práticas de uso do Claude Code

1. **Planeje antes de editar**: modo Plan para qualquer mudança com mais de um arquivo.
2. **Uma tarefa por conversa**: `/clear` ao trocar de assunto; conversa longa perde
   qualidade e gasta mais.
3. **Contexto por referência**: aponte arquivos com `@arquivo` em vez de colar conteúdo.
4. **Delegue exploração a subagentes**: eles leem muito e devolvem só o resumo, poupando
   o contexto principal.
5. **Modelo certo para cada papel**: o mais capaz para arquitetura e revisão; um mais
   rápido para tarefas mecânicas.
6. **Peça verificação, não confiança**: o Claude deve rodar lint, testes e validação e
   mostrar a saída antes de dizer que terminou.
7. **Revise todo diff**: você é o responsável técnico pelo que vai para o cliente.
8. **Plugins de terceiros**: um plugin roda com as suas permissões. Só instale de fonte
   confiável, leia o que ele faz e prefira os oficiais. Popularidade em rede social não
   é critério de segurança.
9. **Dados reais nunca no contexto**: perfil, não amostra (Fase 1.3).
