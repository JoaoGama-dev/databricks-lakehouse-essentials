# 0006. Sem dbt: Lakeflow Spark Declarative Pipelines

- **Status:** aceita
- **Data:** 2026-10-30 (registrada em 2026-11-03)

## Contexto

O pacote Essentials atende pequenas e médias empresas no Azure Databricks do próprio
cliente, com uma equipe enxuta mantendo vários projetos. A transformação precisa de
ingestão incremental de arquivos, regras de qualidade visíveis para o cliente, histórico
SCD tipo 2 e execução serverless, sem uma segunda ferramenta para instalar, versionar e
operar ao lado do Databricks.

## Decisão

Toda a transformação, da bronze à gold, é feita em **Lakeflow Spark Declarative
Pipelines** (antigo DLT), serverless, empacotada no Databricks Asset Bundle: bronze e
silver em Python com `from pyspark import pipelines as dp` (nunca `import dlt`), lógica
específica de fonte e gold em SQL. Não há dbt no projeto.

## Alternativas consideradas

- **dbt (Core ou Cloud) sobre o SQL warehouse:** ótimo para modelagem em SQL, mas não
  cobre a ingestão incremental (Auto Loader), o AUTO CDC nem as expectations com a aba
  Data quality; seria mais uma ferramenta, mais um runtime e mais um lugar para os testes.
- **Notebooks e jobs Spark escritos à mão:** flexíveis, mas sem grafo de dependências,
  sem qualidade declarativa e com o incremental e o histórico implementados por conta
  própria.

## Consequências

- Ingestão, qualidade, CDC e histórico vêm do motor; o projeto escreve só a configuração
  e o que é específico.
- A linhagem, o event log e a aba Data quality ficam no próprio Databricks, onde o
  cliente já está.
- O projeto depende das APIs de pipelines declarativos da Databricks; mudanças de
  sintaxe são conferidas na documentação oficial antes de cada uso (regra 9 do
  `CLAUDE.md`).
- Testes de SQL ficam nos testes de integração (ADR 0005), já que não há `dbt test`.
