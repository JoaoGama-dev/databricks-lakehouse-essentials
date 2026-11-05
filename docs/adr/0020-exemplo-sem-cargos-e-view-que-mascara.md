# 0020. Exemplo sem cargos nem agregada, com área por de-para e view que aplica a máscara

- **Status:** aceita
- **Data:** 2026-11-04

## Contexto

O exemplo tinha duas fontes (a agenda e um cadastro de cargos em tabela), uma dimensão
(`gold_dim_cargo`) e uma agregada mensal (`gold_agg_entrevista_mensal`). O cadastro existia
só para ligar o prefixo da vaga a uma área, e a agregada repetia o que o painel já calcula.
Isso pedia uma origem simulada e muitas tabelas para um exemplo pequeno.

A fato também usava `current_date()` para `fl_sem_retorno`. Uma função não determinística
fora do `WHERE` impede o refresh incremental da materialized view.

Por fim, a máscara de coluna (ADR 0002) fica na fato. Não há garantia documentada de que um
`MASK` de tabela valha para quem lê por uma view.

## Decisão

1. **O exemplo tem uma fonte, a `agenda`.** Saem a fonte `cargos`, a `gold_dim_cargo`, a
   `gold_agg_entrevista_mensal` e o schema de origem. A agregada mensal vira cálculo do
   painel.
2. **A área vem de um de-para de prefixos do nome da vaga, numa CTE da própria
   `gold_fato_entrevista`.** Vale o prefixo mais longo que combinar; sem prefixo conhecido,
   a área é `Não classificada`. Sem função não determinística: o refresh incremental da
   fato foi confirmado no dev (`WINDOW_FUNCTION`).
3. **O painel lê só a view `gold_vw_entrevistas`**, criada pela tarefa `governanca_depois`
   (`src/views/gold_vw_entrevistas.sql`), com `COMMENT` em cada coluna e
   `TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'view')`. Ela traz o que depende de hoje
   (`fl_sem_retorno`, com `current_date()`).
4. **A view aplica a função de máscara** em `nm_candidato` e `nr_telefone` (padrão
   dynamic view), mesmo com o `MASK` já declarado na fato.
5. **Tags do Unity Catalog `camada` e `tipo`** em toda tabela e view publicada, copiadas
   das `TBLPROPERTIES`. Os tipos `view` e `observabilidade` passam a existir.
6. **Sem UDF Python em `src/`:** um teste recusa. A máscara é uma função SQL.

## Alternativas consideradas

- **Manter o cadastro de cargos:** é o jeito certo quando a área muda sozinha pelo negócio.
  Para o exemplo, só acrescentava uma origem e uma dimensão. O de-para fica fácil de trocar
  por uma dimensão quando um cliente precisar.
- **Manter a agregada na gold:** duplica o que o painel calcula e cria mais uma tabela para
  manter.
- **`current_date()` na própria fato:** perde o refresh incremental.
- **Confiar só no `MASK` da fato:** sem garantia documentada para leituras por view. A
  função na view é a defesa que funciona nos dois casos.
- **Função de área em Python (UDF):** tira o código do motor e impede o refresh
  incremental.

## Consequências

- O negócio e o painel leem uma view; a fato fica para quem precisa dela (Genie, SQL).
- Um prefixo de vaga novo exige editar o de-para na gold (PR); a aba **Pendências** do painel
  lista as vagas `Não classificada`.
- A função de máscara roda duas vezes na view (fato e view). Para o tamanho dos projetos do
  pacote, o custo é desprezível.
- Coluna sensível nova precisa do `MASK` na fato **e** da função na view; testes conferem.
- Não foi possível validar a máscara com um segundo usuário no Free Edition; no cliente, valide
  com alguém do grupo de leitura fora do grupo de dados pessoais
  ([`levando-ao-azure.md`](../levando-ao-azure.md)).
- Atualiza o [ADR 0002](0002-dados-pessoais-no-unity-catalog.md) (a máscara vale também na
  view) e o [ADR 0005](0005-testes-de-integracao.md) (a integração não depende mais de uma
  origem simulada).
