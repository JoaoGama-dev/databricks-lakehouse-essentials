# 0009. Expectations em tabela intermediária, nunca na view do AUTO CDC

- **Status:** aceita, atualizada por [0019](0019-silver-unica-scd2-com-retrato-privado.md)
  (o retrato do snapshot é uma materialized view privada do pipeline; as regras continuam
  nele)
- **Data:** 2026-10-30 (registrada em 2026-11-03)

## Contexto

As regras do `fontes.yml` viram expectations: `drop` descarta a linha e `alerta` só
conta. Na primeira versão, elas ficavam na view temporária (`limpa_<fonte>`) que
alimentava o AUTO CDC FROM SNAPSHOT, e o pipeline rodava sem erro, mas **as regras eram
ignoradas sem aviso**: o AUTO CDC FROM SNAPSHOT lê a origem como um retrato e não aplica
nem registra expectations de views. A correção entrou em 2026-10-30, antes do primeiro
PR.

## Decisão

As regras ficam numa **tabela intermediária materializada** antes do AUTO CDC:
`silver_int_<fonte>_retrato` (materialized view, no snapshot) ou
`silver_int_<fonte>_mudancas` (streaming table, no cdc). No modo incremental, ficam na
própria `silver_<fonte>`. A regra `unico` é checada à parte, em
`silver_int_<fonte>_unico_<colunas>`. Qualidade só por expectations: nunca um `WHERE`
que esconda o problema.

## Alternativas consideradas

- **Expectations na view temporária:** é o que falhava em silêncio.
- **Filtrar com `WHERE` antes do AUTO CDC:** descartaria as linhas, mas sem contagem nem
  registro na aba Data quality e no event log.
- **Expectations depois do AUTO CDC, na silver:** a linha inválida (por exemplo, chave
  nula) já teria quebrado ou contaminado o CDC.

## Consequências

- A aba Data quality mostra os descartes e alertas no nó `silver_int_*`, e o event log
  alimenta `mon_qualidade_diaria` (ADR 0003).
- Uma tabela a mais por fonte, com custo de armazenamento pequeno.
- Regra inegociável no `CLAUDE.md` (6) e no `docs/padroes/camadas.md`, conferida por
  teste.
