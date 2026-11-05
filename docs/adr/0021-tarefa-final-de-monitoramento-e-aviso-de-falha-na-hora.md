# 0021. Tarefa final de monitoramento e aviso de falha na hora

- **Status:** aceita
- **Data:** 2026-11-05

## Contexto

O ADR 0015 pôs a tarefa `registrar_falha` no fim do job: ela gravava o motivo em uma tabela
e terminava com erro de propósito. O e-mail com o motivo só saía às 7h, pelo alerta
`falha_carga`. Dois problemas apareceram no dev:

- O serverless **repete tarefas Python que terminam com erro**, e o bundle omite
  `max_retries: 0` (valor zero). A tarefa rodava 3 vezes.
- O Databricks decide o resultado do job pelas **tarefas folha**. Uma tarefa de aviso que
  termina bem deixaria a execução como "Succeeded with failures", sem o aviso nativo.

## Decisão

1. **`publicar_monitoramento`** (`run_if: ALL_DONE`) roda depois de tudo e faz a
   publicação: view da gold, tags, views `mon_*`, `mon_log_execucao`, log legível e o
   motivo seguro de cada falha. **Só termina com erro se uma etapa dela falhar**, para o
   serverless não repetir a tarefa por causa da falha de outra.
2. **`avisar_falha`** (`alert_task` do alerta `falha_carga`, `run_if: AT_LEAST_ONE_FAILED`)
   avalia o alerta na hora. O e-mail sai com o motivo, sem esperar as 7h.
3. **`encerrar_com_falha`** (`sql_task` com `raise_error` de texto fixo) é a folha do job.
   Deixa a execução vermelha e dispara o `on_failure` nativo.
4. **Nomes novos:** `preparar_governanca` (antes `governanca_antes`), `processar_medalhao`
   (antes `atualizar_lakehouse`), `publicar_monitoramento` (antes `governanca_depois`) e
   `ingerir_fontes_externas` (antes `ingestao_banco` e `ingestao_api`).
5. **`mon_falhas` vira uma view** sobre `mon_log_execucao` (ADR 0022). A tabela antiga, se
   existir, é renomeada para `mon_falhas_legado`, nunca apagada.
6. **Mantém do ADR 0015:** `motivo_seguro` (lista de permissões, nunca o registro) e os
   destinatários. O alerta ganha `retrigger_seconds: 3600`: uma nova falha avisa de novo. O
   agendamento das 7h continua como rede de segurança. No `ci` o alerta fica pausado.

## Alternativas consideradas

- **Tarefa que termina com erro para avisar (ADR 0015):** o serverless a repete.
- **`max_retries: 0` no bundle:** o valor zero é omitido; a repetição continua.
- **Só o alerta das 7h:** o motivo chega até 24 horas depois.
- **Enviar o e-mail de dentro da tarefa:** exigiria servidor de e-mail e segredo novo.

## Consequências

- O e-mail com o motivo chega logo depois da falha, e o job fica vermelho.
- `avisar_falha` e `encerrar_com_falha` usam um SQL warehouse. No cliente, use o warehouse
  dedicado do projeto (ADR 0023). O service principal de prod precisa de `CAN_USE` no
  warehouse e `CAN_RUN` no alerta.
- No `ci`, a `avisar_falha` pode mandar e-mail se a integração falhar.
- Atualiza o [ADR 0003](0003-monitoramento-fora-do-pipeline.md) (a tarefa que cria as
  `mon_*`) e o [ADR 0004](0004-ingestao-so-com-fonte.md) (uma tarefa e uma variável).
- Substitui o [ADR 0015](0015-aviso-de-falha-com-motivo.md).
