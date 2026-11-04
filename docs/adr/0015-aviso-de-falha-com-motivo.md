# 0015. Aviso de falha com o motivo, sem dado pessoal

- **Status:** aceita
- **Data:** 2026-11-03

## Contexto

Na sustentação, o chamado de falha crítica é aberto "automaticamente quando um alerta de
falha dispara", com prazo de primeira resposta de 1 dia útil nos planos do Essentials.
O aviso nativo do job (e-mail ou webhook) diz só que a execução falhou: não traz a
mensagem de erro. E a mensagem de erro de uma regra `falhar` traz o **registro** que
violou a regra, que pode ter nome e telefone de uma pessoa.

## Decisão

1. **Tarefa `registrar_falha`** no job, com `run_if: AT_LEAST_ONE_FAILED`, dependendo de
   todas as outras. Para cada tarefa que falhou, lê o erro (do pipeline, pelo event log;
   das tarefas Python, pela saída da execução), passa por `motivo_seguro` e grava em
   `mon_falhas` (data, tarefa, motivo, link da execução).
2. **`motivo_seguro`** nunca repassa o registro: numa regra `falhar`, só o nome da regra
   e a orientação de conferir o arquivo; nos outros erros, só a primeira linha, cortada
   antes de qualquer trecho que pareça um registro, com 300 caracteres no máximo.
3. A tarefa **termina com erro de propósito**: a execução continua marcada como falha e o
   aviso de falha do próprio job também dispara.
4. **Alerta SQL `falha_carga`** às 7h com `{{QUERY_RESULT_TABLE}}`: o e-mail traz a
   tabela das falhas das últimas 24 horas, com o motivo e o link.
5. Destinatários: o usuário do cliente (`usuario_alerta`) e, em prod, o **suporte da
   Logos** por um destino de notificação de e-mail (`destino_suporte_id`), criado pelo
   administrador. O aviso de falha do job vai também para `email_suporte`.

## Alternativas consideradas

- **Só o aviso nativo do job:** sem o motivo, o primeiro passo de todo chamado seria
  abrir a execução para descobrir o erro.
- **Webhook para Teams ou Slack com a mensagem do motor:** levaria o registro com dado
  pessoal para fora do ambiente do cliente.
- **Enviar o e-mail de dentro da tarefa:** exigiria um servidor de e-mail e credenciais
  guardadas; o alerta SQL já entrega e-mail sem segredo novo.

## Consequências

- O motivo chega por e-mail em até um dia (alerta às 7h); a falha em si é avisada na hora
  pelo aviso nativo do job.
- `mon_falhas` vira o histórico de falhas do relatório mensal da sustentação.
- O e-mail de falha do job e o alerta dependem do suporte configurado em prod
  (`email_suporte`, `destino_suporte_id`).
- Testado no cenário v4 da integração: a regra `data_plausivel` para a carga e
  `mon_falhas` guarda só o nome da regra.
