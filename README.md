# Essentials · projeto portfolio

[![CI](https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/actions/workflows/ci.yml/badge.svg)](https://github.com/JoaoGama-dev/databricks-lakehouse-essentials/actions/workflows/ci.yml)

Projeto de portfólio de engenharia de dados: o pacote **Essentials** da Logos Analytics,
um **lakehouse medalhão orientado por metadados** no Databricks, empacotado como
**Databricks Asset Bundle**.

As fontes de cada projeto são descritas em [`config/fontes.yml`](config/fontes.yml). A
bronze e a silver são geradas a partir dele, então reaproveitar o projeto em outro
cliente é, na maior parte, trocar esse arquivo.

- Roda primeiro no **Databricks Free Edition** (target `dev`) e depois no **Azure
  Databricks** de um cliente (target `prod`), mudando só o target.
- **Sem dbt**: tudo em Lakeflow Spark Declarative Pipelines (antigo DLT), serverless.
  Bronze e silver em Python (`from pyspark import pipelines as dp`), lógica específica e
  gold em SQL.
- **ELT**: a bronze guarda o dado exatamente como chegou.
- **Nomes padronizados**: tabelas em `camada_tipo_nome` e colunas com prefixo da classe
  da informação (`dt_`, `nm_`, `st_`, `qt_`...), validados pelos testes.

O exemplo usa duas fontes: a **agenda de entrevistas** de um RH (planilha CSV) e um
**cadastro de cargos** (tabela no Unity Catalog). A gold, em modelo estrela, junta as duas
para mostrar comparecimento e aprovação por área.

## Estrutura do pacote Essentials

Todos os projetos do pacote seguem a mesma organização, para que qualquer pessoa da
equipe encontre as coisas no mesmo lugar.

**No Unity Catalog (Free Edition, target `dev`):**

```
essentials                         ← catálogo do pacote (um só para todos os projetos)
├── portfolio                      ← schema do projeto: bronze, silver e gold
│   └── landing (volume)           ← /Volumes/essentials/portfolio/landing/<fonte>/
└── portfolio_origem               ← sistemas de origem simulados do projeto
```

No ambiente do cliente (target `prod`), o catálogo é o do cliente (`prd`) e o schema
continua sendo o nome do projeto.

**No bundle:** o nome é `essentials_<projeto>` e a variável `projeto` gera o schema, a
landing e os nomes do job (`essentials_<projeto>_carga_diaria`) e do pipeline
(`essentials_<projeto>`). Cada projeto fica numa pasta própria no workspace
(`.bundle/essentials_<projeto>/<target>`).

**Começar um projeto novo do pacote:**

1. Copie este repositório com o nome `essentials-<projeto>`.
2. No `databricks.yml`, troque `bundle.name` para `essentials_<projeto>` e o `default` da
   variável `projeto`.
3. Em `setup/00_setup_free_edition.sql`, troque `portfolio` pelo nome do projeto.
4. Reescreva `config/fontes.yml`, os `src/pipeline/silver_<fonte>.sql` e os
   `src/pipeline/gold_*.sql` (a skill `novo-cliente` do Claude Code conduz esse passo).

### Padrão de nomes das tabelas: `camada_tipo_nome`

| Prefixo | Tipo | Exemplo | Para que serve |
|---|---|---|---|
| `bronze_` | bruta | `bronze_agenda` | dado exatamente como chegou |
| `silver_int_` | intermediária | `silver_int_agenda_retrato` | passos internos; onde ficam as regras de qualidade |
| `silver_` | atual | `silver_agenda` | estado atual de cada registro |
| `silver_..._historico` | histórico | `silver_agenda_historico` | todas as versões (SCD tipo 2) |
| `gold_dim_` | dimensão | `gold_dim_cargo` | cadastros que dão contexto à fato |
| `gold_fato_` | fato | `gold_fato_entrevista` | eventos do negócio, uma linha por evento |
| `gold_agg_` | agregada | `gold_agg_entrevista_mensal` | totais prontos para o painel |

Toda tabela leva `TBLPROPERTIES ('camada' = ..., 'tipo' = ...)` e um `COMMENT`.

### Padrão de nomes das colunas: prefixo da classe da informação

| Prefixo | Tipo | Uso | | Prefixo | Tipo | Uso |
|---|---|---|---|---|---|---|
| `id_` | inteiro/texto | identificador | | `qt_` | inteiro/decimal | quantidade |
| `cd_` | texto/inteiro | código | | `vl_` | decimal/inteiro | valor |
| `nm_` | texto | nome | | `pc_` | decimal | percentual |
| `ds_` | texto | descrição | | `dt_` | data | data |
| `sg_` | texto | sigla | | `dh_` | timestamp | data e hora |
| `st_` | texto | status | | `hr_` | texto | hora (hh:mm) |
| `nr_` | texto/inteiro | número (telefone, documento) | | `fl_` | booleano | flag |

A validação do `fontes.yml` recusa coluna sem prefixo conhecido ou com prefixo que não
combina com o tipo (ex.: `dt_` em texto). Colunas técnicas começam com `_` (`_fonte`,
`_arquivo_origem`, `_ingerido_em`).

## Arquitetura

```
 config/fontes.yml ──(validado por config/fontes.schema.json)──┐
                                                                │ lido por bronze.py e silver.py
 FONTES                         LANDING ZONE                    ▼
 ┌─────────────┐               ┌───────────────────────┐   ┌───────────────────────────────┐
 │ arquivo     │──────────────▶│ /Volumes/.../landing  │──▶│ bronze_<fonte>                │
 │ banco  ─────┼─job ingestão─▶│ (dev)                 │   │ Auto Loader, dado como chegou │
 │ api    ─────┼─job ingestão─▶│ abfss://landing@...   │   │ + _fonte _arquivo_origem      │
 └─────────────┘               │ (prod)                │   │   _ingerido_em                │
 ┌─────────────┐               └───────────────────────┘   └──────────────┬────────────────┘
 │ tabela (UC) │─────────────────────────────────────────▶ bronze_<fonte> │
 └─────────────┘                                            (MV/streaming) │
                                                                           ▼
                          silver_<fonte>.sql (opcional) ──▶ silver_int_<fonte>_preparada
                                                                           ▼
        limpeza padrão, nomes padronizados e regras do YAML como expectations (silver.py)
          incremental: silver_<fonte> · snapshot: silver_int_<fonte>_retrato
          cdc: silver_int_<fonte>_mudancas
                                                                           ▼
                          AUTO CDC (snapshot e cdc): silver_<fonte> (estado atual)
                                               + silver_<fonte>_historico (SCD 2)
                                                                           ▼
                        gold_*.sql: gold_dim_* · gold_fato_* · gold_agg_*
                                                                           ▼
                                        Painel AI/BI (Dashboards + Genie)

 Lakeflow Jobs: essentials_<projeto>_carga_diaria · 6h (America/Sao_Paulo)
   ingestao_api ─┐
                 ├─▶ atualizar_lakehouse (pipeline)
   ingestao_banco┘
```

As regras de qualidade ficam numa tabela intermediária, e não numa view, porque o AUTO
CDC FROM SNAPSHOT lê a origem como um retrato e não aplica expectations de views.

## Fontes do exemplo

| Fonte | Tipo | Modo | Chave | Detalhe |
|---|---|---|---|---|
| `agenda` | arquivo (texto) | snapshot + histórico | `dt_entrevista`, `nm_candidato` | a planilha do ano inteiro é reenviada a cada vez; a data só aparece na linha `AGENDA DIA`, tratada em `silver_agenda.sql` |
| `cargos` | tabela | snapshot | `id_cargo` | `essentials.portfolio_origem.cadastro_cargos`, criada pelo setup; liga o prefixo da vaga a uma área |

## Tabelas geradas

| Tabela | Objeto | Camada · tipo | O que tem |
|---|---|---|---|
| `bronze_agenda` | streaming table | bronze · bruta | cada arquivo da agenda inteiro numa linha (`value`), como chegou |
| `bronze_cargos` | materialized view | bronze · bruta | cópia da tabela de cargos |
| `silver_int_agenda_preparada` | view temporária | silver · intermediária | uma linha por entrevista, com a data do separador repetida |
| `silver_int_agenda_retrato` | materialized view | silver · intermediária | último retrato limpo; **regras de qualidade da agenda** |
| `silver_int_cargos_retrato` | materialized view | silver · intermediária | cadastro limpo; **regras de qualidade dos cargos** |
| `silver_int_cargos_unico_ds_prefixo_vaga` | materialized view | silver · intermediária | checagem da regra `unico` |
| `silver_agenda` | streaming table (AUTO CDC) | silver · atual | estado atual de cada entrevista |
| `silver_agenda_historico` | streaming table (SCD 2) | silver · histórico | cada mudança de status, com `__START_AT` e `__END_AT` |
| `silver_cargos` | streaming table (AUTO CDC) | silver · atual | cadastro atual de cargos |
| `gold_dim_cargo` | materialized view | gold · dimensão | cargos e áreas, com o membro `-1 = Não classificada` |
| `gold_fato_entrevista` | materialized view | gold · fato | entrevista + `id_cargo` + `fl_compareceu`, `fl_aprovado`, `fl_sem_retorno` |
| `gold_agg_entrevista_mensal` | materialized view | gold · agregada | `qt_` por mês, área e status |

### Regras de qualidade da agenda

| Regra | Ação | O que verifica |
|---|---|---|
| `nome_preenchido` | drop | `nm_candidato` preenchido |
| `data_entrevista_valida` | drop | `dt_entrevista` reconhecida (`dd/MM/yyyy` ou `yyyy-MM-dd`) |
| `status_conhecido` | alerta | `st_entrevista` dentro da lista depois do de-para |
| `telefone_valido` | alerta | `nr_telefone` com 10 ou 11 dígitos (um número que o Excel converteu para `4,19E+10` não passa) |
| `horario_valido` | alerta | `hr_entrevista` no formato `HH:mm` |

O status passa por um de-para no YAML (`Aprovada` → `Aprovado`, `N/ atendeu` → `Não
atendeu`, `Cancelou` → `Cancelado`, vazio → `Pendente`), e o telefone sai mascarado
(`(41) ****-1234`) por causa da LGPD. Nos modos snapshot e cdc, toda coluna da chave
precisa de uma regra `nao_nulo` com `drop`: o AUTO CDC não aceita chave nula.

## O `config/fontes.yml`

Cada fonte informa: `nome`, `tipo` (arquivo, tabela, banco ou api), o bloco do tipo,
`modo_carga` (incremental, snapshot ou cdc), `historico`, `chave_primaria`,
`coluna_atualizacao`, `colunas` (nome padronizado, `origem`, tipo, formatos de data,
caixa, de-para, máscara) e `regras` (nao_nulo, valores_aceitos, expressao, unico, com
ação drop ou alerta). Os campos estão explicados nos comentários do próprio arquivo, e o
formato é validado por [`config/fontes.schema.json`](config/fontes.schema.json) no pytest
e no começo de cada execução do pipeline.

| Tipo | Como chega à bronze | Testado em |
|---|---|---|
| `arquivo` | Auto Loader lê a pasta da fonte na landing | Free Edition e Azure |
| `tabela` | lê a tabela do Unity Catalog (MV no snapshot, streaming nos outros modos) | Free Edition e Azure |
| `banco` | `src/ingestao/banco_para_landing.py` lê pelo Lakehouse Federation, com watermark, e grava parquet na landing | **só Azure** |
| `api` | `src/ingestao/api_para_landing.py` chama a API com token do secret scope e grava JSON na landing | **só Azure** |

O Free Edition restringe acesso externo, então `banco` e `api` não foram testados nele.

## Estrutura de pastas

```
.
├── databricks.yml                     # bundle, variáveis (projeto, catálogo) e targets dev/prod
├── config/
│   ├── fontes.yml                     # fontes do projeto (o que muda por cliente)
│   └── fontes.schema.json             # JSON Schema do fontes.yml
├── resources/
│   ├── pipeline.yml                   # pipeline serverless
│   └── job.yml                        # ingestão de banco/api + pipeline, às 6h
├── src/
│   ├── essentials/config_fontes.py    # lê e valida a config; gera expectations, SQL de limpeza e nomes
│   ├── pipeline/
│   │   ├── bronze.py                  # bronze genérica, uma tabela por fonte
│   │   ├── silver.py                  # silver genérica: limpeza, nomes, expectations, AUTO CDC
│   │   ├── silver_agenda.sql          # lógica específica da agenda
│   │   └── gold_entrevistas.sql       # gold_dim_cargo, gold_fato_entrevista, gold_agg_entrevista_mensal
│   └── ingestao/
│       ├── api_para_landing.py
│       └── banco_para_landing.py
├── setup/00_setup_free_edition.sql    # catálogo, schemas, Volume e tabela de cargos
├── data/
│   ├── gerar_dados_exemplo.py         # gera as agendas fictícias v1 e v2
│   └── agenda_exemplo_v*.csv          # saída do gerador (o resto de data/ fica fora do git)
├── tests/                             # pytest, sem Databricks
├── docs/roteiro-de-operacao.md        # guia para o cliente
├── .github/workflows/                 # ci.yml e deploy.yml
├── .claude/skills/                    # nova-fonte e novo-cliente
├── ruff.toml                          # regras de lint
└── CLAUDE.md
```

## Passo a passo no Free Edition

O Free Edition roda **somente os dados fictícios** do gerador
(`data/gerar_dados_exemplo.py`). Os arquivos têm o mesmo formato da planilha real do
RH (cabeçalho, linhas `AGENDA DIA`, `;`, UTF-8 com BOM, CRLF e a mesma sujeira), mas
nomes e telefones inventados. Dados reais de clientes nunca entram aqui: veja
[Dados reais e LGPD](#dados-reais-e-lgpd).

1. **Crie a conta** no [Databricks Free Edition](https://www.databricks.com/learn/free-edition)
   e anote a URL do workspace.
2. **Instale a CLI do Databricks**:
   - Windows: `winget install Databricks.DatabricksCLI`
   - macOS: `brew tap databricks/tap && brew install databricks`
3. **Faça login**: `databricks auth login --host https://<seu-workspace>.cloud.databricks.com`
4. **Configuração local, fora do repositório**: o host do workspace vem do perfil criado
   no login (passo 3), e o e-mail de alerta, da variável `BUNDLE_VAR_alert_email` (no
   PowerShell, `$env:BUNDLE_VAR_alert_email = "voce@exemplo.com"`) ou de
   `--var="alert_email=voce@exemplo.com"` no `deploy`. Nenhum dos dois é versionado.
5. **Rode o setup**: no **SQL Editor**, execute `setup/00_setup_free_edition.sql`. Ele
   cria o catálogo `essentials`, os schemas `essentials.portfolio` e
   `essentials.portfolio_origem`, o Volume `landing` e a tabela `cadastro_cargos`.
6. **Gere as agendas fictícias e envie a versão 1** para a pasta da fonte no Volume. A
   pasta precisa existir antes do envio:
   ```
   python data/gerar_dados_exemplo.py
   databricks fs mkdir dbfs:/Volumes/essentials/portfolio/landing/agenda
   databricks fs cp data/agenda_exemplo_v1.csv dbfs:/Volumes/essentials/portfolio/landing/agenda/
   ```
   O pipeline falha se a pasta estiver vazia, então envie o arquivo antes da primeira
   execução.
7. **Valide, implante e rode**:
   ```
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   databricks bundle run essentials_carga_diaria -t dev
   ```
8. **Confira**: no SQL Editor, consulte `essentials.portfolio.gold_agg_entrevista_mensal`.
   No pipeline, a aba **Data quality** do nó `silver_int_agenda_retrato` mostra as linhas
   descartadas (as 2 entrevistas sem nome do gerador) e os alertas (telefones inválidos,
   status "Talvez", entrevista sem horário).
9. **Segunda carga (snapshot e histórico)**: a versão 2 é a mesma planilha reenviada
   inteira, com o status preenchido nas entrevistas que estavam vazias e mais um dia de
   agenda:
   ```
   databricks fs cp data/agenda_exemplo_v2.csv dbfs:/Volumes/essentials/portfolio/landing/agenda/
   databricks bundle run essentials_carga_diaria -t dev
   ```
   A bronze lê só o arquivo novo, a `silver_agenda` passa de `Pendente` para o status
   preenchido e a `silver_agenda_historico` guarda as duas versões de cada uma. Para
   conferir no SQL Editor:
   ```sql
   -- Entrevistas que mudaram: a versão antiga fechada (__END_AT preenchido) e a nova aberta.
   SELECT dt_entrevista, nm_candidato, st_entrevista, __START_AT, __END_AT
   FROM essentials.portfolio.silver_agenda_historico
   WHERE (dt_entrevista, nm_candidato) IN (
     SELECT dt_entrevista, nm_candidato
     FROM essentials.portfolio.silver_agenda_historico
     GROUP BY ALL HAVING count(*) > 1
   )
   ORDER BY nm_candidato, __START_AT;
   ```

No modo development, o job e o pipeline ganham o prefixo `[dev <usuário>]` e o
agendamento das 6h fica pausado.

## Painel AI/BI

1. No workspace, abra **Dashboards** > **Create dashboard**.
2. Na aba **Data**, adicione `gold_agg_entrevista_mensal`, `gold_fato_entrevista` e
   `gold_dim_cargo`.
3. Peça os gráficos ao **Databricks Assistant**, por exemplo:
   - "Gráfico de barras empilhadas com qt_entrevistas por dt_mes_entrevista, colorido por st_entrevista"
   - "Taxa de comparecimento por nm_area: soma de qt_compareceram dividida pela soma de qt_entrevistas"
   - "Contador de entrevistas com fl_sem_retorno verdadeiro"
   - "Tabela das vagas da fato com id_cargo -1", para completar o cadastro de cargos
4. Publique o painel e, se quiser, ative o **Genie** para perguntas livres.
5. Traga o painel para o bundle:
   ```
   databricks bundle generate dashboard --existing-id <id-do-painel> -t dev
   ```
   O comando cria `resources/<nome>.dashboard.yml` e `src/<nome>.lvdash.json`. Troque o
   `warehouse_id` fixo por uma variável (por exemplo, com `lookup` pelo nome do warehouse)
   para funcionar nos dois targets.

## Levando ao Azure Databricks do cliente

1. **No Azure do cliente**: workspace Azure Databricks Premium com Unity Catalog, conta
   ADLS Gen2 com o contêiner `landing` e um Access Connector.
2. **No Unity Catalog**: storage credential, **external location** para
   `abfss://landing@<conta>.dfs.core.windows.net/`, catálogo `prd` e o schema
   `prd.<projeto>`.
3. **Fontes `tabela`**: troque `{catalogo}.{projeto}_origem...` no `config/fontes.yml`
   pelo nome real da tabela do cliente.
4. **Fontes `banco`**: crie a conexão (`CREATE CONNECTION`) e um catálogo estrangeiro
   **com o mesmo nome** (`CREATE FOREIGN CATALOG ... USING CONNECTION`).
5. **Fontes `api`**: crie o secret scope e guarde o token (`databricks secrets put-secret`).
6. **Service principal** de produção com acesso ao catálogo, à external location, às
   conexões e ao secret scope.
7. **No `databricks.yml`**: preencha o `host` de `prod`, `STORAGEACCOUNT` e o
   `service_principal_name`.
8. **No GitHub**: environment `prod` com revisor obrigatório, variáveis
   `DATABRICKS_HOST_PROD` e `DATABRICKS_CLIENT_ID_PROD` e, no Databricks, a federation
   policy do service principal para o repositório (OIDC).
9. Rode o workflow **Deploy produção** e configure o **Azure Budgets** com o teto do
   diagnóstico.

## CI/CD

| Workflow | Gatilho | O que faz |
|---|---|---|
| `ci.yml` | pull request para a `main` | `ruff check .`, `pytest -q` (inclui a validação do `fontes.yml` e dos padrões de nomes) e `databricks bundle validate -t dev` |
| `deploy.yml` | manual (`workflow_dispatch`) | `bundle validate` e `bundle deploy -t prod` no environment `prod`, com login OIDC |

- `DATABRICKS_HOST_DEV` (variável do repositório) é a URL do workspace de dev; o
  `databricks.yml` não traz o host.
- O Free Edition não oferece service principal com OIDC, por isso o CI de dev usa token.
- Quando houver produção, ative o deploy automático descomentando o `push` em `deploy.yml`.
- Nada é alterado à mão em produção: tudo passa pelo bundle.

## Dados reais e LGPD

- **Dados reais de clientes só rodam no ambiente do cliente** (Azure Databricks, na
  assinatura dele), nunca no Free Edition. O Free Edition é uma conta pessoal fora do
  contrato e do controle do cliente; levar dados pessoais para lá seria um tratamento
  sem base legal.
- **No repositório só entram dados fictícios**: `data/*.csv` está no `.gitignore`, com
  exceção das agendas `agenda_exemplo_v*.csv` do gerador. Isso também impede que o
  bundle envie arquivos reais ao workspace.
- **Na silver, o telefone sai mascarado.** A bronze guarda o dado bruto e deve ter acesso
  restrito à equipe técnica.
- A Logos atua como operadora dos dados, seguindo as instruções do cliente, com acordo
  de confidencialidade assinado antes do diagnóstico.

## Próximos passos

- Completar o cadastro de cargos até zerar as entrevistas com `id_cargo = -1`.
- Painel versionado no bundle.
- Metric views no Unity Catalog para as taxas de comparecimento e aprovação.

## Aviso

O **Databricks Free Edition** é só para aprendizado e uso pessoal e **não pode ser usado
comercialmente**. Projetos de clientes rodam no Azure Databricks do próprio cliente, com
a nuvem paga diretamente à Microsoft.

## Licença

© 2026 João Gama · Logos Analytics. **Todos os direitos reservados.**

Este repositório é público para fins de portfólio: você pode ler e avaliar o código, mas
não pode copiá-lo, modificá-lo, distribuí-lo nem usá-lo comercialmente sem autorização
por escrito. Os projetos de clientes ficam em repositórios privados, no GitHub de cada
cliente.
