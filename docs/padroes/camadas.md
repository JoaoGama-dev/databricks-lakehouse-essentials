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
- Todo arquivo novo em `src/pipeline/` entra sozinho: o pipeline lê a pasta inteira
  (`glob` em `resources/pipeline.yml`). A pasta só pode ter código do pipeline.
- Fontes `banco` e `api` chegam à landing pela tarefa `ingerir_fontes_externas` do job
  (`src/ingestao/ingerir_fontes_externas.py`); só são testadas no Azure (o Free Edition
  restringe acesso externo).

## Bronze

- Dado exatamente como chegou, mais `_fonte`, `_arquivo_origem` e `_modificado_em` (quando
  há arquivo) e `_ingerido_em`. Nenhuma limpeza, nenhum filtro.
- Fica no schema `<projeto>_bronze`, junto do volume `landing` (ADR 0018). A agenda é lida
  como texto, um arquivo por linha (coluna `value`).

## Silver

- **Contrato explícito:** só entram as colunas declaradas no YAML (e as técnicas), na
  ordem do contrato. O que não for declarado fica na bronze.
- **Qualidade só via expectations**, geradas das `regras` do YAML. Nunca filtrar com
  `WHERE` para esconder problema de qualidade.
- **Expectations nunca em view temporária que alimenta AUTO CDC:** o AUTO CDC FROM
  SNAPSHOT ignora as regras de views sem avisar. Elas ficam em
  `silver_int_<fonte>_retrato` (MV, snapshot) ou `silver_int_<fonte>_mudancas`
  (streaming, cdc). No modo incremental, ficam na própria `silver_<fonte>`.
- **O retrato do snapshot é privado do pipeline** (materialized view com `private`): não
  aparece no catálogo nem recebe tag, mas as expectations continuam nele e chegam ao event
  log com o nome dele ([ADR 0019](../adr/0019-silver-unica-scd2-com-retrato-privado.md)).
  A tabela `silver_int_<fonte>_mudancas` (cdc) e as checagens `unico` são publicadas.
- Modos `snapshot` e `cdc` usam AUTO CDC. **Há uma só silver por fonte:** com
  `historico: true`, `silver_<fonte>` é a SCD tipo 2 (`__START_AT` e `__END_AT`; a versão
  vigente tem `__END_AT` vazio); sem ele, é a SCD tipo 1. Não existe
  `silver_<fonte>_historico`. Quem quer o estado atual filtra `__END_AT IS NULL`.
- Fica no schema `<projeto>_silver` (ADR 0018), junto da função `mascarar_dado_pessoal`.
- **A chave é conferida sozinha** (`regras_efetivas`): coluna da chave sem regra
  `nao_nulo` ganha uma com `drop`; no incremental, a chave inteira ganha `unico`. Nos
  modos snapshot e cdc, a regra `nao_nulo` da chave não pode ser só alerta.
- **Ação `falhar`** só para o que indica arquivo errado (a carga inteira para e o aviso de
  falha dispara com o motivo, ADR 0021); linha ruim é `drop` ou `alerta`.
- Na bronze de arquivo, o Auto Loader roda em modo `rescue` (CSV, JSON, Parquet): coluna
  nova na origem não derruba a carga e aparece em `mon_estrutura` (ADR 0014).
- **Data de referência (snapshot de arquivos):** o retrato é o arquivo com a maior
  `data_referencia` do `fontes.yml` (`ingestao`, padrão; `conteudo`, com uma expressão SQL
  agregada; ou `nome_arquivo`, com regex de um grupo e formato), não o último ingerido. O
  desempate é, em ordem: data de referência, modificação do arquivo na landing
  (`_modificado_em`), `_ingerido_em` e nome do arquivo; a ordem de envio vale, sem depender
  dos micro-batches ([ADR 0024](../adr/0024-integracao-em-duas-rodadas-e-desempate-pelo-arquivo.md)).
  Como o retrato é privado, os avisos acham o arquivo dele pelas versões vigentes
  da silver. A
  `expressao` é código executável: revise como código no PR. O arquivo recebido que não
  virou retrato aparece em `mon_estrutura` como `arquivo_ignorado`, e texto que não é UTF-8 válido, como
  `codificacao_invalida` ([ADR 0016](../adr/0016-data-de-referencia-do-snapshot.md)).
- **Full refresh não apaga o histórico:** a bronze de arquivo, banco e API e o histórico
  SCD2 levam `pipelines.reset.allowed = false` ([ADR 0017](../adr/0017-retencao-e-exclusao-de-titular.md)).
  Com isso, o Databricks recusa o full refresh do grafo inteiro; reprocesse com
  `--full-refresh` só nas tabelas que podem ser recriadas.
  **Mudar o schema da bronze é manual:** remova a propriedade com decisão registrada, faça a
  mudança e a restaure (passo a passo em [`retencao-e-exclusao.md`](retencao-e-exclusao.md)).
- **Lógica específica de uma fonte** fica em `src/pipeline/silver_<fonte>.sql`, como a
  view temporária `silver_int_<fonte>_preparada`, com `preparacao_sql: true` no YAML. Nela
  vai só o que a limpeza padrão não cobre (ex.: estrutura do arquivo).

## Gold

- SQL em `src/pipeline/gold_*.sql`, em modelo estrela (dim e fato; agregada só quando o
  cálculo no painel ficar caro). Fica no schema `<projeto>_gold`, o único que o negócio lê.
- Regra de negócio (ex.: situação concluído, em andamento, pendente; a área da vaga por
  de-para) fica na gold, não no painel.
- **Sem função não determinística** (`current_date`, `current_timestamp`...) fora do `WHERE`
  numa materialized view: ela perde o refresh incremental. No exemplo, o refresh incremental
  da fato foi confirmado no dev (`WINDOW_FUNCTION`).
- **Sem UDF Python** em `src/`: um teste recusa. Use SQL e funções nativas.
- **Views da gold** (`src/views/gold_vw_*.sql`) trazem o que depende de hoje e são o que o
  painel lê. São criadas pela tarefa `publicar_monitoramento`, com `COMMENT` por coluna, porque a
  view de pipeline não aplica o `COMMENT` de cada coluna. Toda coluna sensível passa pela
  função de máscara na view ([ADR 0020](../adr/0020-exemplo-sem-cargos-e-view-que-mascara.md)).

## Monitoramento

- O pipeline publica o event log em `mon_log_eventos`, no schema
  `<projeto>_monitoramento`. As views `mon_*` (qualidade
  diária, atualização, volume, estrutura, execuções e custo) são geradas por
  `src/essentials/monitoramento_sql.py` e criadas pela tarefa `publicar_monitoramento`, fora
  do pipeline (ADR 0003 e 0021).
- **Log da carga:** `mon_log_execucao` é uma tabela (tipo `observabilidade`), com uma linha
  por execução e nível (job, tarefa e tabela). É criada pela `preparar_governanca` e gravada
  pela `publicar_monitoramento`, por MERGE pela chave; nunca é recriada. O log por tabela
  vem do event log: não ponha código de log dentro das tabelas do pipeline (ADR 0022).
  `mon_falhas` é uma view sobre ela.
- **Log legível:** toda tarefa Python usa `configurar_log` (`src/essentials/log_texto.py`),
  no formato `[AAAA-MM-DD hh:mm:ss]-[NIVEL]: mensagem` e no fuso da variável `fuso_horario`.
  A mensagem só leva nomes, status, contagens, tempos e o motivo já limpo por
  `motivo_seguro`; nunca o valor de um registro.
- **Custo:** `mon_custo_*` atribuem pela tag `projeto`, em todos os ambientes; o warehouse
  só entra com `warehouse_dedicado` igual a `"true"` (ADR 0023).
- As `mon_*` leem **metadados** (event log, `information_schema`, tabelas de sistema), com
  duas exceções: `codificacao_invalida` e `arquivo_ignorado` leem a bronze (só um arquivo e
  uma coluna) e nunca mostram dado de linha.
- Mensagem de erro nunca sai do ambiente sem passar por `motivo_seguro` (LGPD).
- Regra nova no `fontes.yml` entra sozinha em `mon_qualidade_diaria`, com a ação do YAML.
- Fonte `banco` ou `api` nova: troque `ingerir_fontes_externas` para `"true"` no
  `databricks.yml` (um teste confere; ADR 0004).

## Dicionário de dados (obrigatório)

- Toda coluna da silver tem `descricao` no `fontes.yml`; vira `COMMENT` pelo schema do
  contrato em `silver.py`.
- Toda tabela da gold declara as colunas com tipo e `COMMENT`, na ordem do `SELECT`; toda
  `gold_vw_*` declara `COMMENT` em cada coluna.
- Toda tabela e view tem `COMMENT` e `TBLPROPERTIES ('camada', 'tipo')`; a governança copia
  os dois para as tags do Unity Catalog.
- As views `mon_*` também: `COMMENT` em cada coluna e `TBLPROPERTIES` com
  `'camada' = 'monitoramento'`.

## Painel AI/BI

- `src/dashboards/*.lvdash.json` + `resources/dashboard.yml`. As consultas não citam
  catálogo nem schema (`dataset_catalog`/`dataset_schema` no bundle). O painel do negócio
  (`painel_negocio`, `negocio.lvdash.json`, do projeto)
  lê só views `gold_vw_*`; o de saúde da plataforma lê só as views `mon_*`, do schema
  `<projeto>_monitoramento`. Agregações (por mês, por área) são calculadas nos datasets do
  painel.
