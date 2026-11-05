# 0023. Custo do projeto por tag e projeção do mês

- **Status:** aceita
- **Data:** 2026-11-05

## Contexto

O ADR 0003 atribuía o custo pelos IDs do job e do pipeline do target atual. Assim, o custo
do `ci` e do `prod` ficava fora, e um recurso recriado (o `ci` ganha IDs novos a cada
rodada) sumia do histórico. Também não havia projeção do mês nem custo de cada carga. O
faturamento do warehouse não traz a tag `projeto`.

## Decisão

1. **`mon_custo_diario` atribui pela tag `projeto`:** jobs pela cobrança e por
   `system.lakeflow.jobs`; pipelines por `system.lakeflow.pipelines`. Cobre `dev`, `ci` e
   `prod`, com o ambiente pela tag `ambiente`. Preço de lista.
2. **Warehouse só com a variável `warehouse_dedicado` = `"true"`** (padrão `"false"`). No
   cliente, o recomendado é um warehouse exclusivo do projeto. No Free Edition ele é
   compartilhado e fica fora, como o armazenamento e a otimização preditiva.
3. **`mon_custo_mensal`** por ambiente e total, com a projeção do mês (custo médio dos dias
   com uso vezes os dias do mês; a do total é a soma das projeções dos ambientes). O alerta
   `custo_teto` lê a linha `total`.
4. **`mon_custo_por_carga`:** custo de lista de cada execução (job e pipeline, com as novas
   tentativas e o uso por hora rateado).
5. **Permissão:** o service principal de prod precisa de `SELECT` em `system.billing` e
   `system.lakeflow` (concessão do metastore admin). Sem isso as views de custo não são
   criadas e o log mostra só um aviso.

## Alternativas consideradas

- **IDs do target atual (ADR 0003):** não cobre os outros ambientes nem recursos recriados.
- **Incluir sempre o warehouse:** no Free Edition ele é compartilhado e o custo de outros
  usos entraria no projeto.
- **Só a política de uso serverless:** é configuração do administrador da conta; fica como
  complemento.

## Consequências

- Números do dev em 2026-11-05 (preço de lista): cerca de US$ 0,12 por carga no `dev` e
  US$ 0,17 no `ci`. Para uma carga diária de volume parecido, US$ 3 a 6 por mês de job e
  pipeline, mais warehouse e armazenamento.
- Uma carga que falha custou cerca de US$ 0,70 no `ci`, por causa das novas tentativas do
  pipeline.
- A tag `projeto` deve ser imposta por política no cliente; sem ela, o custo some da conta.
- `warehouse_dedicado` = `"true"` só com warehouse exclusivo.
- Atualiza o [ADR 0003](0003-monitoramento-fora-do-pipeline.md).
