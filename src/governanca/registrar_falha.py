"""Registra o motivo de uma falha da carga diária, como tarefa do job (docs/adr/0015).

Roda só quando alguma tarefa falhou (run_if: AT_LEAST_ONE_FAILED). Para cada tarefa que
falhou, lê o erro (do pipeline, pelo event log; das tarefas Python, pela saída da
execução), limpa a mensagem com motivo_seguro (nunca o registro que violou a regra, por
LGPD) e grava em mon_falhas. O alerta SQL "falha_carga" manda essa tabela por e-mail.

Termina com erro de propósito: assim a execução continua marcada como falha e o aviso de
falha do próprio job também dispara.
"""

from __future__ import annotations

import argparse
import sys

# Tarefas que falharam por conta própria; UPSTREAM_FAILED é só consequência de outra falha.
ESTADOS_DE_FALHA = {"FAILED", "TIMEDOUT", "CANCELED"}
# Esta própria tarefa termina com erro de propósito: nunca é registrada como falha.
TAREFA_PROPRIA = "registrar_falha"


def tarefas_com_falha(tarefas) -> list:
    """Tarefas da execução que falharam, sem a própria registrar_falha."""
    return [
        tarefa
        for tarefa in tarefas or []
        if tarefa.task_key != TAREFA_PROPRIA
        and tarefa.state
        and tarefa.state.result_state
        and tarefa.state.result_state.value in ESTADOS_DE_FALHA
    ]


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codigo", required=True, help="pasta src/ do bundle")
    parser.add_argument("--catalogo", required=True)
    parser.add_argument(
        "--schema-monitoramento", required=True, help="schema de monitoramento (event log e mon_falhas)"
    )
    parser.add_argument("--run-id", required=True, help="execução do job ({{job.run_id}})")
    return parser.parse_args()


def erro_do_pipeline(spark, catalogo: str, schema: str) -> str | None:
    """Erros da última atualização com falha do pipeline, pelo event log publicado."""
    linhas = spark.sql(
        f"""SELECT concat_ws(' ', message, to_json(error)) AS texto
        FROM `{catalogo}`.`{schema}`.mon_log_eventos
        WHERE level = 'ERROR' AND origin.update_id = (
          SELECT origin.update_id FROM `{catalogo}`.`{schema}`.mon_log_eventos
          WHERE event_type = 'update_progress' AND details:update_progress:state = 'FAILED'
          ORDER BY timestamp DESC LIMIT 1)
        ORDER BY timestamp"""
    ).collect()
    return "\n".join(linha["texto"] for linha in linhas) or None


def main() -> None:
    args = argumentos()
    sys.path.append(args.codigo)
    from databricks.sdk import WorkspaceClient
    from pyspark.sql import SparkSession

    from essentials.monitoramento_sql import TABELA_FALHAS, motivo_seguro, sql_registrar_falhas

    spark = SparkSession.builder.getOrCreate()
    w = WorkspaceClient()
    execucao = w.jobs.get_run(int(args.run_id))
    link = f"{w.config.host.rstrip('/')}/jobs/{execucao.job_id}/runs/{execucao.run_id}"

    falhas = []
    for tarefa in tarefas_com_falha(execucao.tasks):
        mensagem = tarefa.state.state_message
        if tarefa.pipeline_task:
            mensagem = erro_do_pipeline(spark, args.catalogo, args.schema_monitoramento) or mensagem
        else:
            saida = w.jobs.get_run_output(tarefa.run_id)
            mensagem = saida.error or mensagem
        falhas.append((tarefa.task_key, motivo_seguro(mensagem)))
    if not falhas:
        falhas.append(("desconhecida", motivo_seguro(None)))

    spark.sql(sql_registrar_falhas(args.catalogo, args.schema_monitoramento, str(execucao.run_id), falhas, link))
    resumo = "; ".join(f"{tarefa}: {motivo}" for tarefa, motivo in falhas)
    print(f"Falha registrada em {TABELA_FALHAS}: {resumo}")
    sys.exit(f"Carga com falha (registrada em {TABELA_FALHAS}): {resumo}")


if __name__ == "__main__":
    main()
