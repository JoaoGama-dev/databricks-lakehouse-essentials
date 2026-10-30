# essentials_lakehouse

Projeto de portfólio de engenharia de dados: o pacote **Essentials** da Logos Analytics,
um **lakehouse medalhão orientado por metadados** no Databricks, empacotado como
**Databricks Asset Bundle**.

As fontes de cada cliente são descritas em [`config/fontes.yml`](config/fontes.yml). A
bronze e a silver são geradas a partir dele, então reaproveitar o projeto em outro
cliente é, na maior parte, trocar esse arquivo.

- Roda primeiro no **Databricks Free Edition** (target `dev`) e depois no **Azure
  Databricks** de um cliente (target `prod`), mudando só o target.
- **Sem dbt**: tudo em Lakeflow Spark Declarative Pipelines (antigo DLT), serverless.
  Bronze e silver em Python (`from pyspark import pipelines as dp`), lógica específica e
  gold em SQL.
- **ELT**: a bronze guarda o dado exatamente como chegou.

O exemplo usa duas fontes: a **agenda de entrevistas** de um RH (planilha CSV) e um
**cadastro de cargos** (tabela no Unity Catalog). A gold junta as duas para mostrar
comparecimento e aprovação por área.

## Arquitetura

```
 config/fontes.yml ──(validado por config/fontes.schema.json)──┐
                                                                │ lido por bronze.py e silver.py
 FONTES                         LANDING ZONE                    ▼
 ┌─────────────┐               ┌───────────────────────┐   ┌───────────────────────────────┐
 │ arquivo     │──────────────▶│ /Volumes/.../landing  │──▶│ bronze_<nome>                 │
 │ banco  ─────┼─job ingestão─▶│ (dev)                 │   │ Auto Loader, dado como chegou │
 │ api    ─────┼─job ingestão─▶│ abfss://landing@...   │   │ + _fonte _arquivo_origem      │
 └─────────────┘               │ (prod)                │   │   _ingerido_em                │
 ┌─────────────┐               └───────────────────────┘   └──────────────┬────────────────┘
 │ tabela (UC) │─────────────────────────────────────────▶ bronze_<nome>  │
 └─────────────┘                                            (MV/streaming) │
                                                                           ▼
                                   silver_<nome>.sql (opcional) ──▶ preparada_<nome>
                                                                           ▼
                         limpeza padrão + expectations das regras do YAML (silver.py)
                                                                           ▼
                incremental: append  ·  snapshot: AUTO CDC FROM SNAPSHOT  ·  cdc: AUTO CDC
                     silver_<nome> (estado atual)  +  silver_<nome>_historico (SCD 2)
                                                                           ▼
                                  gold_*.sql: materialized views com junções
                                                                           ▼
                                        Painel AI/BI (Dashboards + Genie)

 Lakeflow Jobs: essentials_carga_diaria · 6h (America/Sao_Paulo)
   ingestao_api ─┐
                 ├─▶ atualizar_lakehouse (pipeline)
   ingestao_banco┘
```

## Fontes do exemplo

| Fonte | Tipo | Modo | Chave | Detalhe |
|---|---|---|---|---|
| `agenda` | arquivo (texto) | snapshot + histórico | `data_entrevista`, `nome_candidato` | a planilha do ano inteiro é reenviada a cada vez; a data só aparece na linha `AGENDA DIA`, tratada em `silver_agenda.sql` |
| `cargos` | tabela | snapshot | `id_cargo` | `workspace.origem.cadastro_cargos`, criada pelo setup; liga o prefixo da vaga a uma área |

## Tabelas geradas

| Tabela | Tipo | Camada | O que tem |
|---|---|---|---|
| `bronze_agenda` | streaming table | bronze | cada arquivo da agenda inteiro numa linha (`value`), como chegou |
| `bronze_cargos` | materialized view | bronze | cópia da tabela de cargos |
| `preparada_agenda` | view temporária | — | uma linha por entrevista, com a data do separador repetida |
| `limpa_agenda`, `limpa_cargos` | views temporárias | — | limpeza padrão + expectations; alimentam o AUTO CDC |
| `silver_agenda` | streaming table (AUTO CDC) | silver | estado atual de cada entrevista |
| `silver_agenda_historico` | streaming table (SCD 2) | silver | cada mudança de status, com `__START_AT` e `__END_AT` |
| `silver_cargos` | streaming table (AUTO CDC) | silver | cadastro atual de cargos |
| `silver_cargos_unico_prefixo_vaga` | materialized view | silver | checagem da regra `unico` |
| `gold_entrevistas` | materialized view | gold | entrevista + área + `compareceu`, `aprovado`, `sem_retorno` |
| `gold_indicadores_entrevistas` | materialized view | gold | totais por mês, área e status |

### Regras de qualidade da agenda

| Regra | Ação | O que verifica |
|---|---|---|
| `nome_preenchido` | drop | nome do candidato preenchido |
| `data_entrevista_valida` | drop | data reconhecida (`dd/MM/yyyy` ou `yyyy-MM-dd`) |
| `status_conhecido` | alerta | status dentro da lista depois do de-para |
| `telefone_valido` | alerta | telefone com 10 ou 11 dígitos (um número que o Excel converteu para `4,19E+10` não passa) |
| `horario_valido` | alerta | horário no formato `HH:mm` |

O status passa por um de-para no YAML (`Aprovada` → `Aprovado`, `N/ atendeu` → `Não
atendeu`, `Cancelou` → `Cancelado`, vazio → `Pendente`), e o telefone sai mascarado
(`(41) ****-1234`) por causa da LGPD.

## O `config/fontes.yml`

Cada fonte informa: `nome`, `tipo` (arquivo, tabela, banco ou api), o bloco do tipo,
`modo_carga` (incremental, snapshot ou cdc), `historico`, `chave_primaria`,
`coluna_atualizacao`, `colunas` (limpeza padrão: tipo, formatos de data, caixa, de-para,
máscara) e `regras` (nao_nulo, valores_aceitos, expressao, unico, com ação drop ou
alerta). Os campos estão explicados nos comentários do próprio arquivo, e o formato é
validado por [`config/fontes.schema.json`](config/fontes.schema.json) no pytest e no
começo de cada execução do pipeline.

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
├── databricks.yml                     # bundle, variáveis e targets dev/prod
├── config/
│   ├── fontes.yml                     # fontes do cliente (o que muda por cliente)
│   └── fontes.schema.json             # JSON Schema do fontes.yml
├── resources/
│   ├── pipeline.yml                   # pipeline serverless
│   └── job.yml                        # ingestão de banco/api + pipeline, às 6h
├── src/
│   ├── essentials/config_fontes.py    # lê e valida a config; gera expectations e SQL de limpeza
│   ├── pipeline/
│   │   ├── bronze.py                  # bronze genérica, uma tabela por fonte
│   │   ├── silver.py                  # silver genérica: limpeza, expectations, AUTO CDC
│   │   ├── silver_agenda.sql          # lógica específica da agenda
│   │   └── gold_entrevistas.sql       # junção agenda x cargos e indicadores
│   └── ingestao/
│       ├── api_para_landing.py
│       └── banco_para_landing.py
├── setup/00_setup_free_edition.sql    # schema, Volume e tabela de cargos
├── data/
│   ├── gerar_dados_exemplo.py         # gera as agendas fictícias v1 e v2
│   └── agenda_exemplo_v*.csv          # saída do gerador (o resto de data/ fica fora do git)
├── tests/                             # pytest, sem Databricks
├── docs/roteiro-de-operacao.md        # guia para o cliente
├── .github/workflows/                 # ci.yml e deploy.yml
├── .claude/skills/                    # nova-fonte e novo-cliente
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
4. **Ajuste o `databricks.yml`**: troque o `host` do target `dev` pela URL do seu
   workspace e o `default` de `alert_email` pelo seu e-mail.
5. **Rode o setup**: no **SQL Editor**, execute `setup/00_setup_free_edition.sql`. Ele
   cria o schema `workspace.essentials`, o Volume `landing` e a tabela
   `workspace.origem.cadastro_cargos`.
6. **Gere as agendas fictícias e envie a versão 1** para a pasta da fonte no Volume:
   ```
   python data/gerar_dados_exemplo.py
   databricks fs cp data/agenda_exemplo_v1.csv dbfs:/Volumes/workspace/essentials/landing/agenda/
   ```
   O pipeline falha se a pasta estiver vazia, então envie o arquivo antes da primeira
   execução.
7. **Valide, implante e rode**:
   ```
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   databricks bundle run essentials_carga_diaria -t dev
   ```
8. **Confira**: no SQL Editor, consulte `workspace.essentials.gold_indicadores_entrevistas`.
   No pipeline, a aba **Data quality** do nó `limpa_agenda` mostra as linhas descartadas
   (sem nome, sem data) e os alertas (telefones inválidos etc.).
9. **Segunda carga (snapshot e histórico)**: a versão 2 é a mesma planilha reenviada
   inteira, com o status preenchido nas entrevistas que estavam vazias e mais um dia de
   agenda:
   ```
   databricks fs cp data/agenda_exemplo_v2.csv dbfs:/Volumes/workspace/essentials/landing/agenda/
   databricks bundle run essentials_carga_diaria -t dev
   ```
   A bronze lê só o arquivo novo, a `silver_agenda` passa de `Pendente` para o status
   preenchido e a `silver_agenda_historico` guarda as duas versões de cada uma.

No modo development, o job e o pipeline ganham seu nome como prefixo e o agendamento
das 6h fica pausado.

## Painel AI/BI

1. No workspace, abra **Dashboards** > **Create dashboard**.
2. Na aba **Data**, adicione `gold_indicadores_entrevistas` e `gold_entrevistas`.
3. Peça os gráficos ao **Databricks Assistant**, por exemplo:
   - "Gráfico de barras empilhadas com total de entrevistas por mês, colorido por status"
   - "Taxa de comparecimento por área: soma de total_compareceram dividida pela soma de total_entrevistas"
   - "Contador de entrevistas com sem_retorno verdadeiro"
   - "Tabela das vagas com área Não classificada", para completar o cadastro de cargos
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
   `abfss://landing@<conta>.dfs.core.windows.net/`, catálogo `prd` e schema `prd.essentials`.
3. **Fontes `tabela`**: troque `{catalogo}.origem...` no `config/fontes.yml` pelo nome real
   da tabela do cliente, ou crie-a em `prd.origem`.
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
| `ci.yml` | pull request para a `main` | `ruff check .`, `pytest -q` (inclui a validação do `fontes.yml`) e `databricks bundle validate -t dev` |
| `deploy.yml` | manual (`workflow_dispatch`) | `bundle validate` e `bundle deploy -t prod` no environment `prod`, com login OIDC |

- `DATABRICKS_HOST_DEV` precisa ter o mesmo valor do `host` do target `dev`.
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

- Completar o cadastro de cargos até zerar as vagas `Não classificada`.
- Painel versionado no bundle.
- Metric views no Unity Catalog para as taxas de comparecimento e aprovação.

## Aviso

O **Databricks Free Edition** é só para aprendizado e uso pessoal e **não pode ser usado
comercialmente**. Projetos de clientes rodam no Azure Databricks do próprio cliente, com
a nuvem paga diretamente à Microsoft.
