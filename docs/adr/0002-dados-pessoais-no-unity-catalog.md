# 0002. Dados pessoais no Unity Catalog: máscara de coluna e tags

- **Status:** aceita, atualizada por [0020](0020-exemplo-sem-cargos-e-view-que-mascara.md)
  (a view da gold aplica a mesma função de máscara; a função fica no schema da silver)
- **Data:** 2026-11-03

## Contexto

Até a Fase 2, a única proteção de dado pessoal era o mascaramento fixo na silver
(`mascarar` no `fontes.yml`): o telefone vira `(41) ****-1234` para todo mundo, inclusive
para quem precisa do número, e o nome do candidato ficava visível a qualquer leitor da
gold. O plano pedia avaliar as máscaras de coluna do Unity Catalog, que mostram o dado
para quem tem direito e escondem dos demais, e marcar as colunas pessoais com tags.

Um teste no Free Edition mostrou:

| Operação | Resultado |
| --- | --- |
| Criar a função de máscara (SQL UDF) | funciona |
| `ALTER TABLE ... ALTER COLUMN ... SET TAGS` numa tabela do pipeline | funciona |
| `ALTER TABLE ... ALTER COLUMN ... SET MASK` numa tabela do pipeline | recusado: tabelas do pipeline (materialized views e streaming tables) não aceitam `ALTER COLUMN` |
| Máscara declarada na definição da tabela (`MASK` na lista de colunas) | funciona |

## Decisão

1. **Flag `sensivel: true`** por coluna no `fontes.yml` marca o dado pessoal; toda coluna
   com `mascarar` precisa dela (a validação recusa o contrário).
2. **Máscara de coluna na gold**, declarada no próprio pipeline: as colunas sensíveis da
   gold (`nm_candidato`, `nr_telefone`) usam `MASK <catálogo>.<projeto>.mascarar_dado_pessoal`.
   A função devolve o valor para quem é do `grupo_dados_pessoais` e `****` para os demais.
   Ela é criada pela tarefa `governanca_antes` do job, antes do pipeline.
3. **O mascaramento fixo na silver continua** para o telefone: é a defesa mais forte
   (o número completo nem chega à silver). A máscara de coluna é uma segunda camada, na
   gold, que é o único lugar que o negócio lê (ADR 0001).
4. **Tag `pii` = `true`** em toda coluna sensível da silver (atual, histórico e retrato) e
   nas colunas de mesmo nome da gold, aplicada pela tarefa `governanca_depois`. Tabelas
   internas do Databricks (`__materialization_*`) ficam de fora.

## Alternativas consideradas

- **Máscara de coluna também na silver:** a silver está num schema só da engenharia; a
  máscara ali só atrapalharia quem mantém o pipeline. Fica como opção se, no cliente, a
  silver for aberta a mais gente.
- **Só o mascaramento fixo na silver:** simples, mas impede que o RH, que precisa do nome
  para ligar ao candidato, use o painel. Rejeitada como única proteção.
- **Aplicar a máscara depois com `ALTER`:** não é aceito em tabelas do pipeline.

## Consequências

- O mesmo painel mostra o nome para o grupo de dados pessoais e `****` para os demais,
  sem duplicar tabelas.
- Coluna sensível nova na gold precisa declarar o `MASK` (um teste confere).
- As tags `pii` permitem localizar todo dado pessoal pelo `information_schema.column_tags`
  e servem de base para políticas e auditoria no cliente.
- **Limitação no Free Edition:** só existe um usuário, então não dá para ver a máscara do
  lado de quem não tem acesso; foi conferido que a máscara está registrada
  (`information_schema.column_masks`) e que o usuário do grupo vê os valores. No cliente,
  validar com um usuário do grupo de leitura que não esteja no de dados pessoais.
