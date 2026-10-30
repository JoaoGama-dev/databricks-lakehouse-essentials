# Regras do projeto essentials_portfolio

Projeto do pacote Essentials: lakehouse medalhão orientado por metadados,
empacotado como Databricks Asset Bundle. Roda no Free Edition (target `dev`) e no
Azure Databricks do cliente (target `prod`).

## Estrutura do pacote Essentials
- Catálogo `essentials` (dev) ou o do cliente (prod); **um schema por projeto**
  (`<projeto>`, com o volume `landing`) e `<projeto>_origem` para origens simuladas.
- Bundle `essentials_<projeto>`; a variável `projeto` gera schema, landing e os nomes do
  job e do pipeline. Nunca escreva o nome do projeto fixo no código: use `${var.projeto}`
  ou o marcador `{projeto}` do `fontes.yml`.

## Padrão de nomes
- **Tabelas `camada_tipo_nome`**: `bronze_<fonte>`, `silver_int_<fonte>_<passo>`
  (intermediárias), `silver_<fonte>`, `silver_<fonte>_historico`, `gold_dim_<nome>`,
  `gold_fato_<nome>`, `gold_agg_<nome>`. Fato e dimensão no singular.
- Toda tabela com `TBLPROPERTIES ('camada' = ..., 'tipo' = ...)`; tipos válidos em
  `TIPOS_DE_TABELA` (`src/essentials/config_fontes.py`).
- **Colunas com prefixo da classe da informação**: `id_ cd_ nm_ ds_ sg_ st_ nr_ qt_ vl_
  pc_ dt_ dh_ hr_ fl_` (tabela e tipos aceitos em `PREFIXOS_POR_TIPO`). Vale para silver
  e gold; a bronze e as views de preparação mantêm os nomes da origem. Colunas técnicas
  começam com `_`.

## Orientado por metadados
- **As fontes do cliente ficam em `config/fontes.yml`.** Trocar de cliente é trocar
  esse arquivo (mais as SQLs específicas e a gold). Ele é validado por
  `config/fontes.schema.json`; um campo novo exige atualizar o schema, os comentários
  do YAML e `src/essentials/config_fontes.py`.
- A lógica que vem da config (nomes de tabelas, expectations, expressões de limpeza)
  fica em `src/essentials/config_fontes.py`, sem Spark, para ser testada pelo pytest.
- `src/pipeline/bronze.py` e `src/pipeline/silver.py` são genéricos: não colocar neles
  nada específico de uma fonte.

## Camadas
- **Sem dbt.** Tudo em Lakeflow Spark Declarative Pipelines, serverless. Python com
  `from pyspark import pipelines as dp`; nunca `import dlt`.
- **Bronze sem transformação**: dado exatamente como chegou, mais `_fonte`,
  `_arquivo_origem` (quando há arquivo) e `_ingerido_em`.
- **Qualidade só via expectations na silver**, geradas das `regras` do YAML.
  Não filtrar dados com `WHERE` para esconder problemas de qualidade.
- **Expectations nunca em view temporária que alimenta AUTO CDC**: o AUTO CDC FROM
  SNAPSHOT ignora as regras de views sem avisar. Elas ficam em `silver_int_<fonte>_retrato`
  (MV, snapshot) ou `silver_int_<fonte>_mudancas` (streaming, cdc).
- **Lógica específica de uma fonte** fica em `src/pipeline/silver_<nome>.sql`, como a
  view temporária `silver_int_<nome>_preparada`, com `preparacao_sql: true` no YAML. Nela
  vai só o que a limpeza padrão não cobre (ex.: estrutura do arquivo); TRIM, tipos,
  de-para, nomes padronizados e regras continuam no YAML.
- Modos `snapshot` e `cdc` usam AUTO CDC; `historico: true` cria `silver_<nome>_historico`
  (SCD tipo 2). Cada coluna da chave precisa de regra `nao_nulo` com `drop`.
- **Gold em SQL**, em `src/pipeline/gold_*.sql`, em modelo estrela (dim, fato, agg).
- **COMMENT obrigatório** em toda tabela.
- **Dicionário de dados obrigatório**: toda coluna da silver tem `descricao` no
  `fontes.yml` (vira `COMMENT` pelo schema do contrato em `silver.py`), e toda view da
  gold declara as colunas com tipo e `COMMENT`, na ordem do `SELECT`. A silver só recebe
  colunas declaradas; o que não for declarado fica na bronze.
- Todo arquivo novo em `src/pipeline/` entra nas `libraries` de `resources/pipeline.yml`.
- Fontes `banco` e `api` chegam à landing pelos jobs de `src/ingestao/`; só são
  testadas no Azure (o Free Edition restringe acesso externo).

## Dados e LGPD
- Dados de clientes nunca vão para o repositório: `data/*.csv` está no `.gitignore`.
  Só as agendas fictícias do gerador (`data/agenda_exemplo_v*.csv`) são versionadas.
- **O Free Edition roda só dados fictícios.** Dados reais rodam apenas no ambiente
  Azure do cliente. Nunca escreva nomes, telefones ou outros dados reais em README,
  comentários, testes ou exemplos.
- Telefones e outros dados pessoais saem mascarados da silver em diante (`mascarar`).

## Ambientes
- **Nunca alterar produção à mão.** Tudo passa pelo bundle e pelo workflow de deploy.
- Caminhos e catálogos vêm das variáveis do `databricks.yml`; nada fixo no código.

## Lint
- Regras do ruff em `ruff.toml` (E, W, F, I, B, UP, BLE, RUF). Não use `# noqa` sem
  necessidade nem `except Exception`: capture a exceção específica.
- Versões das ferramentas fixadas em `requirements-dev.txt` e nos workflows.

## Antes de propor uma mudança
Liste para o usuário os comandos que ele deve rodar (não rode você mesmo):

```
ruff check .
pytest -q
databricks bundle validate -t dev
```

## Idioma
Tudo em português do Brasil: comentários, documentação, mensagens e nomes de colunas
em snake_case.
