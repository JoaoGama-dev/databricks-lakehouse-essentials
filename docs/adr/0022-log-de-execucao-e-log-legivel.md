# 0022. mon_log_execucao e log legível

- **Status:** aceita
- **Data:** 2026-11-05

## Contexto

Para saber o que uma carga fez, era preciso abrir o job, o pipeline e o event log. Faltava
um lugar só com quanto tempo cada passo levou, que método de carga foi usado, quantas
linhas entraram, foram descartadas ou geraram alerta, e quando a tabela tinha sido
atualizada antes. O texto de saída das tarefas também não tinha padrão.

## Decisão

1. **Tabela `mon_log_execucao`** no schema `<projeto>_monitoramento`, com tipo
   `observabilidade`. Uma linha por execução e nível: `job`, `tarefa` e `tabela`.
2. **Colunas:** início, fim, duração em segundos e em `hh:mm:ss`, status, método de carga
   (`APPEND (Auto Loader)`, `AUTO CDC FROM SNAPSHOT SCD2`, `MATERIALIZED VIEW`, `VIEW`),
   técnica de refresh escolhida pelo motor (`COMPLETE_RECOMPUTE`, `WINDOW_FUNCTION`,
   `ROW_BASED`, `NO_OP`...), linhas gravadas, descartadas e em alerta (soma das violações),
   total na tabela, última atualização anterior, motivo seguro e link.
3. **O log por tabela vem do event log**, no fim da carga, pela `publicar_monitoramento`.
   O pipeline é declarativo: não há código nosso por tabela. As expectations do retrato
   privado são atribuídas à `silver_agenda`.
4. **Gravação por MERGE idempotente** pela chave: rodar a mesma execução de novo não
   duplica. A tabela nunca é recriada.
5. **Log legível** na saída de toda tarefa Python: `[AAAA-MM-DD hh:mm:ss]-[NIVEL]: mensagem`,
   no fuso da variável `fuso_horario` (`America/Sao_Paulo`).
6. **LGPD:** o motivo passa por `motivo_seguro` (lista de permissões). O texto de erro do
   motor nunca é gravado; o log e o e-mail não levam valor de registro.

## Alternativas consideradas

- **Só o event log:** tem os dados, mas por atualização do pipeline, sem job nem tarefa e
  sem duração legível.
- **Código nosso dentro de cada tabela:** o pipeline é declarativo e o código por tabela
  quebraria o acelerador por metadados.
- **View em vez de tabela:** recalcularia a cada leitura e não guardaria o motivo seguro,
  que só existe na hora da carga.

## Consequências

- Um lugar só responde "o que rodou, quanto levou e o que entrou". O painel "Saúde da
  carga" lê a tabela.
- `qt_linhas_alerta` soma violações: uma linha que viola duas regras conta duas vezes.
- Os números do retrato privado aparecem na linha da `silver_agenda`.
- Complementa o [ADR 0003](0003-monitoramento-fora-do-pipeline.md) e o
  [ADR 0021](0021-tarefa-final-de-monitoramento-e-aviso-de-falha-na-hora.md).
