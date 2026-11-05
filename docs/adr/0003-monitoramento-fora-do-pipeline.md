# 0003. Monitoramento em views fora do pipeline, sobre o event log publicado

- **Status:** aceita, atualizada por [0018](0018-schemas-por-camada.md) (o event log, as
  `mon_*` e o painel de saúde ficam no schema `<projeto>_monitoramento`, só da engenharia),
  por [0021](0021-tarefa-final-de-monitoramento-e-aviso-de-falha-na-hora.md) (a tarefa
  `governanca_depois` virou `publicar_monitoramento`), por
  [0022](0022-log-de-execucao-e-log-legivel.md) (log da carga) e por
  [0023](0023-custo-do-projeto-por-tag-e-projecao.md) (o custo passa a ser atribuído pela tag
  `projeto`, não pelos IDs)
- **Data:** 2026-11-03

## Contexto

Até a Fase 3, a qualidade dos dados só aparecia na aba Data quality de cada atualização
do pipeline: não havia histórico, nem como saber se a carga parou de rodar, nem quanto o
projeto custa. O plano pedia publicar o event log, criar `mon_qualidade_diaria` e
`mon_atualizacao` e decidir se elas ficam dentro do pipeline ou fora.

O teste em dev mostrou:

- O `event_log` do pipeline (catálogo, schema e nome) pode ser ligado num pipeline que já
  existe, sem `full_refresh`. A tabela publicada traz também os eventos das atualizações
  anteriores.
- O event log informa, por expectation, as linhas **aprovadas** e **reprovadas**, mas não
  a ação (`drop` ou alerta).
- As tabelas de sistema de faturamento (`system.billing.usage` e `list_prices`) ficam
  acessíveis no Free Edition. Os registros trazem o ID do job e do pipeline; as tags do
  bundle chegam ao faturamento do job serverless, mas não ao do pipeline.

## Decisão

1. **Event log publicado** em `<catálogo>.<schema do projeto>.mon_log_eventos`. O schema é
   só da engenharia (ADR 0001): o event log pode trazer mensagens de erro com trechos do
   dado.
2. **Views `mon_*` fora do pipeline**, criadas pela tarefa `governanca_depois` do job,
   depois de cada atualização:
   - `mon_qualidade_diaria`: por dia, tabela e regra, a última atualização do dia. A ação
     de cada regra vem do `fontes.yml` (as reprovadas viram descartadas ou alertas).
   - `mon_atualizacao`: última atualização do pipeline concluída e último `_ingerido_em`
     de cada silver. O atraso é medido pelo **pipeline**, não pelo `_ingerido_em`, que
     só muda quando chega arquivo novo.
   - `mon_custo_diario`: DBUs e custo de lista do job e do pipeline, **filtrando pelos
     IDs** dos dois. Sem acesso às tabelas de sistema, a view fica de fora com um aviso e a
     carga não falha.
3. **Alerta SQL** (`resources/alertas.yml`) às 9h sobre `mon_atualizacao`, para um usuário
   do workspace (variável `usuario_alerta`): o Alert v2 não aceita e-mail que não seja de
   usuário, só usuário ou destino de notificação. Em dev fica pausado.
4. **Painel separado "Saúde da plataforma"**, sobre o schema do projeto, só para a
   engenharia. Uma página no painel de entrevistas exigiria publicar as `mon_*` na gold.

## Alternativas consideradas

- **Views dentro do pipeline:** na primeira atualização o event log ainda não existe e o
  grafo falharia; e o pipeline passaria a ler a própria saída de execução.
- **Atraso por `_ingerido_em`:** daria alarme falso nos dias em que o cliente não envia
  planilha, com a carga funcionando.
- **Tarefa de verificação no job em vez de alerta SQL:** não avisa quando o job nem roda,
  que é justamente um dos casos de atraso.
- **Custo pelas tags:** as tags não chegam ao faturamento serverless do pipeline. Pela
  documentação da Databricks, no serverless as tags só são garantidas por uma política de
  uso serverless (antiga *budget policy*) aplicada ao job e ao pipeline; ficam como
  complemento, e a política é configuração do administrador da conta no cliente.

## Consequências

- O histórico de qualidade acompanha o event log: quanto ele guarda, a view mostra.
- Regra renomeada ou removida do `fontes.yml` aparece com ação `desconhecida` nos dias
  antigos.
- Rodar a carga mais de uma vez no mesmo dia: a view mostra só a última atualização do
  dia, como a aba Data quality.
- No cliente, a identidade do job precisa de `SELECT` em `system.billing` para a view de
  custo; e o `usuario_alerta` de prod precisa ser um usuário do workspace (ou trocado por
  um destino de notificação).
