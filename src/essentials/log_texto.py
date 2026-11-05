"""Log legível das tarefas Python do job, no fuso do projeto (variável fuso_horario).

Formato de cada linha: [2026-11-04 06:00:12]-[INFO]: mensagem

Funções puras, testadas pelo pytest. Todas as tarefas Python do job chamam configurar_log;
a publicar_monitoramento imprime o resumo da carga com mensagens_do_log, a partir das linhas
gravadas em mon_log_execucao.

LGPD: as mensagens só levam nomes de tarefa, schema e tabela, status, contagens, datas,
durações e o motivo já limpo por motivo_seguro. Nunca o valor de um registro.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FORMATO = "[%(asctime)s]-[%(levelname)s]: %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"
FUSO_PADRAO = "America/Sao_Paulo"
NOME_DO_LOG = "essentials"
SEM_VALOR = "-"
# Resultados que contam como erro no log legível (job, tarefa e tabela).
RESULTADOS_DE_ERRO = {"FAILED", "TIMEDOUT", "CANCELED"}


def fuso(nome: str | None) -> tzinfo:
    """Fuso pelo nome IANA; nome desconhecido (ou sem base de fusos) cai em UTC.

    Melhor um horário em UTC, com o aviso de configurar_log, que a tarefa parar por causa do log.
    """
    try:
        return ZoneInfo(nome or FUSO_PADRAO)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def formatador(nome_fuso: str | None = FUSO_PADRAO) -> logging.Formatter:
    """Formatter com o formato do pacote e a data no fuso do projeto."""
    formato = logging.Formatter(FORMATO, FORMATO_DATA)
    zona = fuso(nome_fuso)
    # O logging chama converter(segundos) com o instante do registro, sem fuso.
    formato.converter = lambda instante: datetime.fromtimestamp(instante, zona).timetuple()
    return formato


def configurar_log(nome_fuso: str | None = FUSO_PADRAO, saida=None) -> logging.Logger:
    """Logger do pacote, escrevendo na saída da tarefa (stdout) no formato FORMATO."""
    logger = logging.getLogger(NOME_DO_LOG)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for anterior in list(logger.handlers):
        logger.removeHandler(anterior)
    destino = logging.StreamHandler(saida or sys.stdout)
    destino.setFormatter(formatador(nome_fuso))
    logger.addHandler(destino)
    if fuso(nome_fuso) is UTC and (nome_fuso or FUSO_PADRAO) != "UTC":
        logger.warning("Fuso %s não encontrado: horários do log em UTC.", nome_fuso)
    return logger


def data_hora(milissegundos, nome_fuso: str | None = FUSO_PADRAO) -> str:
    """Instante em milissegundos (unix_millis) no fuso do projeto; vazio vira SEM_VALOR."""
    if milissegundos is None:
        return SEM_VALOR
    return datetime.fromtimestamp(int(milissegundos) / 1000, fuso(nome_fuso)).strftime(FORMATO_DATA)


def _texto(valor) -> str:
    return SEM_VALOR if valor is None or valor == "" else str(valor)


def _nivel(resultado: str | None) -> int:
    return logging.ERROR if resultado in RESULTADOS_DE_ERRO else logging.INFO


def _nome_da_tabela(linha: dict) -> str:
    return ".".join(parte for parte in (linha.get("nm_schema"), linha.get("nm_tabela")) if parte)


def mensagens_do_log(linhas: list[dict], nome_fuso: str | None = FUSO_PADRAO) -> list[tuple[int, str]]:
    """(nível do logging, mensagem) do resumo da carga, na ordem de leitura.

    linhas: as de sql_linhas_da_execucao (datas em milissegundos). Ordem: início do job; por
    tabela, como começou e como terminou; status e duração de cada tarefa; cada erro com o
    motivo seguro; fim do job com a duração.
    """
    jobs = [linha for linha in linhas if linha.get("cd_nivel") == "job"]
    tabelas = [linha for linha in linhas if linha.get("cd_nivel") == "tabela"]
    tarefas = [linha for linha in linhas if linha.get("cd_nivel") == "tarefa"]
    mensagens: list[tuple[int, str]] = []
    for job in jobs:
        mensagens.append((
            logging.INFO,
            f"Início do job {_texto(job.get('nm_job'))} (execução {_texto(job.get('id_execucao_job'))}): "
            f"{data_hora(job.get('nr_ms_inicio'), nome_fuso)}",
        ))
    for tabela in tabelas:
        nome = _nome_da_tabela(tabela)
        mensagens.append((
            logging.INFO,
            f"Tabela {nome} | método: {_texto(tabela.get('ds_metodo_carga'))} | técnica: "
            f"{_texto(tabela.get('cd_tecnica_refresh'))} | última atualização anterior: "
            f"{data_hora(tabela.get('nr_ms_ultima_anterior'), nome_fuso)} | início: "
            f"{data_hora(tabela.get('nr_ms_inicio'), nome_fuso)}",
        ))
        mensagens.append((
            _nivel(tabela.get("st_execucao")),
            f"Tabela {nome} | status: {_texto(tabela.get('st_execucao'))} | gravadas: "
            f"{_texto(tabela.get('qt_linhas_gravadas'))} | descartadas: {_texto(tabela.get('qt_linhas_descartadas'))} "
            f"| alertas: {_texto(tabela.get('qt_linhas_alerta'))} | total na tabela: "
            f"{_texto(tabela.get('qt_linhas_tabela'))} | duração: {_texto(tabela.get('ds_duracao'))} | término: "
            f"{data_hora(tabela.get('nr_ms_fim'), nome_fuso)}",
        ))
    for tarefa in tarefas:
        mensagens.append((
            _nivel(tarefa.get("st_execucao")),
            f"Tarefa {_texto(tarefa.get('nm_tarefa'))} | status: {_texto(tarefa.get('st_execucao'))} | duração: "
            f"{_texto(tarefa.get('ds_duracao'))}",
        ))
    for linha in tarefas + tabelas:
        if linha.get("ds_motivo_falha"):
            onde = _texto(linha.get("nm_tarefa"))
            if linha.get("cd_nivel") == "tabela":
                onde = f"{onde} ({_nome_da_tabela(linha)})"
            mensagens.append((logging.ERROR, f"Falha em {onde}: {linha['ds_motivo_falha']}"))
    for job in jobs:
        mensagens.append((
            _nivel(job.get("st_execucao")),
            f"Fim do job {_texto(job.get('nm_job'))} | status: {_texto(job.get('st_execucao'))} | duração: "
            f"{_texto(job.get('ds_duracao'))} | término: {data_hora(job.get('nr_ms_fim'), nome_fuso)}",
        ))
    return mensagens
