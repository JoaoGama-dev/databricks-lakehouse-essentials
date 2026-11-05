-- Última tarefa do job (encerrar_com_falha): só roda quando a carga falhou, depois do
-- e-mail com o motivo (avisar_falha). O Databricks decide o resultado da execução pelas
-- tarefas folha: sem esta, a avisar_falha terminaria bem e a execução ficaria "Succeeded
-- with failures", sem o aviso de falha do próprio job (docs/adr/0015).
SELECT raise_error('A carga diária falhou: o motivo está em mon_falhas e foi enviado por e-mail pela tarefa avisar_falha.');
