# Camadas, qualidade e dicionário de dados

## Orientado por metadados

- As fontes do projeto ficam em `config/fontes.yml`, validado por
  `config/fontes.schema.json`. Um campo novo exige atualizar o schema, os comentários do
  YAML e `src/essentials/config_fontes.py`.
- A lógica que vem da config (nomes de tabelas, expectations, expressões de limpeza,
  schema da silver) fica em `src/essentials/config_fontes.py`, sem Spark, para ser
  testada pelo pytest.
- `src/pipeline/bronze.py` e `src/pipeline/silver.py` são genéricos: nada específico de
  uma fonte entra neles.

## Pipeline

- **Sem dbt.** Tudo em Lakeflow Spark Declarative Pipelines, serverless. Python com
  `from pyspark import pipelines as dp`; nunca `import dlt`.
- Todo arquivo novo em `src/pipeline/` entra nas `libraries` de `resources/pipeline.yml`.
- Fontes `banco` e `api` chegam à landing pelos jobs de `src/ingestao/`; só são testadas
  no Azure (o Free Edition restringe acesso externo).

## Bronze

- Dado exatamente como chegou, mais `_fonte`, `_arquivo_origem` (quando há arquivo) e
  `_ingerido_em`. Nenhuma limpeza, nenhum filtro.

## Silver

- **Contrato explícito:** só entram as colunas declaradas no YAML (e as técnicas), na
  ordem do contrato. O que não for declarado fica na bronze.
- **Qualidade só via expectations**, geradas das `regras` do YAML. Nunca filtrar com
  `WHERE` para esconder problema de qualidade.
- **Expectations nunca em view temporária que alimenta AUTO CDC:** o AUTO CDC FROM
  SNAPSHOT ignora as regras de views sem avisar. Elas ficam em
  `silver_int_<fonte>_retrato` (MV, snapshot) ou `silver_int_<fonte>_mudancas`
  (streaming, cdc). No modo incremental, ficam na própria `silver_<fonte>`.
- Modos `snapshot` e `cdc` usam AUTO CDC; `historico: true` cria
  `silver_<fonte>_historico` (SCD tipo 2). Cada coluna da chave precisa de regra
  `nao_nulo` com `drop`.
- **Lógica específica de uma fonte** fica em `src/pipeline/silver_<fonte>.sql`, como a
  view temporária `silver_int_<fonte>_preparada`, com `preparacao_sql: true` no YAML. Nela
  vai só o que a limpeza padrão não cobre (ex.: estrutura do arquivo).

## Gold

- SQL em `src/pipeline/gold_*.sql`, em modelo estrela (dim, fato, agg).
- Regra de negócio (ex.: situação concluído, em andamento, pendente) fica na gold, não no
  painel.

## Monitoramento

- O pipeline publica o event log em `mon_log_eventos`. As views `mon_*` (qualidade
  diária, atualização e custo) são geradas por `src/essentials/monitoramento_sql.py` e
  criadas pela tarefa `governanca_depois`, fora do pipeline (ADR 0003).
- Regra nova no `fontes.yml` entra sozinha em `mon_qualidade_diaria`, com a ação do YAML.
- Fonte `banco` ou `api` nova: troque `ingerir_banco`/`ingerir_api` para `"true"` no
  `databricks.yml` (um teste confere; ADR 0004).

## Dicionário de dados (obrigatório)

- Toda coluna da silver tem `descricao` no `fontes.yml`; vira `COMMENT` pelo schema do
  contrato em `silver.py`.
- Toda view da gold declara as colunas com tipo e `COMMENT`, na ordem do `SELECT`.
- Toda tabela tem `COMMENT`.
- As views `mon_*` também: `COMMENT` em cada coluna e `TBLPROPERTIES` com
  `'camada' = 'monitoramento'`.

## Painel AI/BI

- `src/dashboards/*.lvdash.json` + `resources/dashboard.yml`. As consultas não citam
  catálogo nem schema (`dataset_catalog`/`dataset_schema` no bundle). O painel do negócio
  lê só tabelas `gold_`; o de saúde da plataforma lê só as views `mon_*`, do schema do
  projeto.
