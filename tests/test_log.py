"""Testes do log da carga (mon_log_execucao), do log legível e do job que os grava.

Cada teste protege contra um risco: log duplicado ou errado (diagnóstico errado), job verde
com a carga quebrada (ninguém é avisado), e-mail de falha que não sai, dado pessoal no log
ou no e-mail (LGPD) e histórico de falhas apagado.
"""

from __future__ import annotations

import io
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from essentials.config_fontes import PREFIXOS_POR_TIPO, TIPOS_DE_TABELA, carregar_fontes
from essentials.log_sql import (
    LOG,
    TABELA_FALHAS,
    TAREFA_PIPELINE,
    TAREFA_PROPRIA,
    decidir_encerramento,
    linhas_de_execucao,
    precisa_renomear_falhas,
    sql_criar_tabela_log,
    sql_merge_execucao,
    sql_merge_tabelas,
    sql_renomear_falhas_legado,
    sql_view_falhas,
    tabelas_privadas,
    tarefas_com_falha,
)
from essentials.log_texto import FORMATO, configurar_log, data_hora, mensagens_do_log
from essentials.monitoramento_sql import regras_monitoradas

RAIZ = Path(__file__).resolve().parents[1]
FONTES = carregar_fontes(RAIZ / "config" / "fontes.yml")
MON = "portfolio_monitoramento"


def carregar_yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def job() -> dict:
    return carregar_yaml(RAIZ / "resources" / "job.yml")["resources"]["jobs"]["essentials_carga_diaria"]


def tarefas() -> dict[str, dict]:
    return {tarefa["task_key"]: tarefa for tarefa in job()["tasks"]}


def bundle() -> dict:
    return carregar_yaml(RAIZ / "databricks.yml")


# Tabela de log -----------------------------------------------------------------------------


def test_tabela_de_log_nunca_e_recriada_e_segue_o_dicionario():
    # CREATE OR REPLACE apagaria o histórico de todas as cargas a cada execução.
    sql = sql_criar_tabela_log("essentials", MON)
    assert sql.startswith(f"CREATE TABLE IF NOT EXISTS `essentials`.`{MON}`.`mon_log_execucao` (")
    assert "OR REPLACE" not in sql
    assert "\nCLUSTER BY AUTO\n" in sql
    assert "TBLPROPERTIES ('camada' = 'monitoramento', 'tipo' = 'observabilidade')" in sql
    assert LOG.tipo in TIPOS_DE_TABELA
    # Dicionário obrigatório (regra 7): toda coluna com prefixo da classe e descrição.
    prefixos = "|".join(PREFIXOS_POR_TIPO)
    for coluna, (_tipo, descricao) in LOG.colunas.items():
        assert re.match(rf"^({prefixos})_", coluna), coluna
        assert descricao.strip(), coluna
        assert f"`{coluna}` " in sql


def test_merge_e_idempotente_pela_chave_com_job_e_tarefa_sem_tabela():
    # Rodar de novo a mesma execução (reparo do job) não pode duplicar linhas: as de job e de
    # tarefa não têm tabela, e a de job não tem tarefa, por isso o coalesce nas duas.
    sql = sql_merge_execucao("essentials", MON, "42", "carga", "https://x", [])
    assert "ON t.id_execucao_job = s.id_execucao_job AND t.cd_nivel = s.cd_nivel" in sql
    assert "coalesce(t.nm_tarefa, '') = coalesce(s.nm_tarefa, '')" in sql
    assert "coalesce(t.nm_tabela, '') = coalesce(s.nm_tabela, '')" in sql
    assert "WHEN MATCHED THEN UPDATE SET" in sql and "WHEN NOT MATCHED THEN INSERT" in sql


def merge_tabelas(**campos) -> str:
    argumentos = {
        "publicadas": [("portfolio_silver", "silver_agenda", "historico")],
        "privadas": tabelas_privadas(FONTES),
        "regras": regras_monitoradas(FONTES),
    } | campos
    return sql_merge_tabelas("essentials", MON, "42", "carga", "https://x", "upd-1", **argumentos)


@pytest.mark.parametrize("tipo", ["execucao", "tabelas"])
def test_merge_entrega_toda_coluna_do_log(tipo):
    # Uma coluna sem valor na origem derruba o MERGE no Databricks: sem log, sem o motivo e sem
    # o e-mail de falha (a view mon_falhas lê o log).
    sql = sql_merge_execucao("essentials", MON, "42", "carga", "https://x", []) if tipo == "execucao" else (
        merge_tabelas()
    )
    selecao = sql.rsplit("\nSELECT ", 1)[1].split("\nFROM ", 1)[0]
    for coluna in LOG.colunas:
        assert re.search(rf"(\bAS {coluna}\b|\.{coluna}\b)", selecao), coluna


def test_linhas_de_tabela_saem_so_da_atualizacao_desta_execucao():
    # Ler o event log inteiro misturaria cargas de dias diferentes na mesma linha.
    sql = merge_tabelas()
    log = "`essentials`.`portfolio_monitoramento`.`mon_log_eventos`"
    # O event log é lido uma vez só, já filtrado pela atualização; o resto lê a CTE eventos.
    assert sql.count(log) == 1
    assert f"SELECT * FROM {log} WHERE origin.update_id = 'upd-1'" in sql


def test_log_de_tabela_nunca_grava_o_texto_do_erro_do_motor():
    # LGPD: message e error podem trazer o registro que violou a regra. Da mensagem só sai a
    # técnica de refresh (só letras maiúsculas e _); error nunca é lido aqui.
    sql = merge_tabelas()
    assert not re.search(r"\berror\b", sql)
    assert len(re.findall(r"\bmessage\b", sql)) == 1
    assert "regexp_extract(message, 'planned to be executed as ([A-Z_]+)', 1)" in sql


def test_retrato_privado_aparece_na_silver_publicada_e_nunca_como_linha():
    # O retrato não está no catálogo: os descartes e alertas dele precisam aparecer na silver,
    # e uma linha com o nome dele seria uma tabela que ninguém acha.
    assert tabelas_privadas(FONTES) == [("silver_int_agenda_retrato", "silver_agenda")]
    sql = merge_tabelas()
    assert "('silver_int_agenda_retrato', 'silver_agenda')" in sql
    assert "coalesce(pv.nm_tabela_publicada, f.nm_saida) AS nm_tabela" in sql
    assert "JOIN publicadas p ON p.nm_schema = t.nm_schema AND p.nm_tabela = t.nm_tabela" in sql
    # Gravadas: a da própria tabela; sem ela (AUTO CDC não informa), a do retrato.
    assert ("coalesce(sum(qt_linhas_gravadas) FILTER (WHERE NOT fl_privada), "
            "sum(qt_linhas_gravadas) FILTER (WHERE fl_privada))") in sql


def test_alertas_somam_so_as_regras_com_acao_alerta():
    # Somar drop ou falhar como alerta daria o número errado no log e no painel.
    regras = regras_monitoradas(FONTES)
    assert ("silver_int_agenda_retrato", "nome_preenchido", "drop") in regras
    assert ("silver_int_agenda_retrato", "data_plausivel", "falhar") in regras
    sql = merge_tabelas(regras=regras)
    assert "AND r.ds_acao = 'alerta'" in sql
    assert "sum(e.regra.failed_records) AS qt_linhas_alerta" in sql


def test_ultima_atualizacao_anterior_e_uma_carga_concluida_antes_desta():
    # Sem os filtros, a própria execução (rodada de novo) ou uma carga com falha viraria a "anterior".
    sql = merge_tabelas()
    trecho = sql[sql.index("anteriores AS (") : sql.index("\n)\nSELECT")]
    assert "l.cd_nivel = 'tabela'" in trecho and "l.st_execucao = 'COMPLETED'" in trecho
    assert "l.dh_fim < t.dh_inicio" in trecho and "l.id_execucao_job <> '42'" in trecho


def test_full_refresh_aparece_como_metodo_antes_do_tipo_do_fluxo():
    sql = merge_tabelas()
    caso = sql[sql.index("CASE\n    WHEN a.fl_full_refresh") :]
    assert caso.index("'FULL_REFRESH'") < caso.index("'APPEND (Auto Loader)'")
    assert "WHEN t.cd_tipo_fluxo = 'SNAPSHOT_CHANGE' AND p.ds_tipo_tabela = 'historico' THEN " \
           "'AUTO CDC FROM SNAPSHOT SCD2'" in sql


def test_view_de_falhas_mantem_as_colunas_do_alerta_e_uma_linha_por_tarefa():
    # O alerta falha_carga lê dh_falha, nm_tarefa, ds_motivo e ds_link: sem elas, o e-mail quebra.
    alerta = carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]["falha_carga"]
    lidas = re.search(r"SELECT (.+)\n", alerta["query_text"]).group(1).split(", ")
    sql = sql_view_falhas("essentials", MON)
    for coluna in lidas:
        assert f"`{coluna}` COMMENT" in sql, coluna
    # Só a linha da tarefa: a linha da tabela repete o motivo e mandaria o e-mail em dobro.
    assert "WHERE cd_nivel = 'tarefa' AND ds_motivo_falha IS NOT NULL" in sql
    assert "TBLPROPERTIES ('camada' = 'monitoramento', 'tipo' = 'falha')" in sql


@pytest.mark.parametrize(("tipo", "renomeia"), [(None, False), ("VIEW", False), ("MANAGED", True)])
def test_tabela_antiga_de_falhas_e_renomeada_nunca_apagada(tipo, renomeia):
    assert precisa_renomear_falhas(tipo) is renomeia
    sql = sql_renomear_falhas_legado("essentials", MON)
    assert sql == (
        f"ALTER TABLE `essentials`.`{MON}`.`{TABELA_FALHAS}` RENAME TO `essentials`.`{MON}`.`mon_falhas_legado`"
    )


# Job e tarefas -------------------------------------------------------------------------------


def tarefa_api(chave: str, resultado: str | None, inicio: int = 1_000, fim: int = 61_000, tentativa: int = 0):
    estado = SimpleNamespace(result_state=SimpleNamespace(value=resultado) if resultado else None)
    return SimpleNamespace(task_key=chave, state=estado, start_time=inicio, end_time=fim, attempt_number=tentativa)


def execucao_api(*tarefas_da_execucao) -> SimpleNamespace:
    return SimpleNamespace(start_time=500, tasks=list(tarefas_da_execucao))


def por_tarefa(linhas: list[tuple]) -> dict[str | None, tuple]:
    return {linha[1]: linha for linha in linhas}


def test_job_fica_failed_quando_uma_tarefa_falha_e_success_com_ingestao_pulada():
    ok = execucao_api(
        tarefa_api("tem_fonte_externa", "SUCCESS"),
        tarefa_api("ingerir_fontes_externas", "EXCLUDED", 0, 0),
        tarefa_api(TAREFA_PIPELINE, "SUCCESS"),
        tarefa_api(TAREFA_PROPRIA, None, 70_000, 0),
        tarefa_api("avisar_falha", None, 0, 0),
    )
    linhas = linhas_de_execucao(ok, {}, "upd-1", 90_000, [])
    assert linhas[0] == ("job", None, "upd-1", 500, 90_000, "SUCCESS", None)
    # Tarefa pulada: sem início nem fim (a API manda 0), nada de duração negativa.
    assert por_tarefa(linhas)["ingerir_fontes_externas"][3:5] == (None, None)
    # A avisar_falha ainda não rodou: não entra.
    assert "avisar_falha" not in por_tarefa(linhas)
    assert por_tarefa(linhas)[TAREFA_PIPELINE][2] == "upd-1"

    falhou = execucao_api(tarefa_api(TAREFA_PIPELINE, "FAILED"), tarefa_api(TAREFA_PROPRIA, None, 70_000, 0))
    linhas = linhas_de_execucao(falhou, {TAREFA_PIPELINE: "Regra violada"}, None, 90_000, [])
    assert linhas[0][5] == "FAILED"
    assert por_tarefa(linhas)[TAREFA_PIPELINE][5:] == ("FAILED", "Regra violada")
    # A própria tarefa termina agora e com o resultado das etapas dela.
    assert por_tarefa(linhas)[TAREFA_PROPRIA][3:] == (70_000, 90_000, "SUCCESS", None)


def test_erro_numa_etapa_da_publicacao_tambem_marca_o_job_como_falha():
    execucao = execucao_api(tarefa_api(TAREFA_PIPELINE, "SUCCESS"), tarefa_api(TAREFA_PROPRIA, None, 70_000, 0))
    linhas = linhas_de_execucao(execucao, {}, "upd-1", 90_000, ["views mon"])
    assert linhas[0][5] == "FAILED"
    propria = por_tarefa(linhas)[TAREFA_PROPRIA]
    assert propria[5] == "FAILED" and "views mon" in propria[6]


def test_falha_conta_a_ultima_tentativa_e_nunca_a_consequencia_nem_a_propria():
    tarefas_da_execucao = [
        tarefa_api(TAREFA_PIPELINE, "FAILED", tentativa=0),
        tarefa_api(TAREFA_PIPELINE, "SUCCESS", tentativa=1),
        tarefa_api("preparar_governanca", "TIMEDOUT"),
        tarefa_api("ingerir_fontes_externas", "UPSTREAM_FAILED"),
        tarefa_api(TAREFA_PROPRIA, "FAILED"),
    ]
    assert [t.task_key for t in tarefas_com_falha(tarefas_da_execucao)] == ["preparar_governanca"]


def test_decisao_de_terminar_com_erro():
    # Sem falha: a tarefa não pode falhar (job vermelho e e-mail de falha à toa todo dia).
    assert decidir_encerramento([], []) is None
    mensagem = decidir_encerramento([(TAREFA_PIPELINE, "Regra de qualidade que para a carga foi violada: x.")], [])
    assert mensagem.startswith("A carga diária falhou (processar_medalhao: Regra de qualidade")
    assert "mon_falhas" in mensagem
    assert TAREFA_PROPRIA in decidir_encerramento([], ["log da carga"])


# Log legível ---------------------------------------------------------------------------------


def test_log_legivel_no_formato_e_no_fuso_do_projeto():
    saida = io.StringIO()
    logger = configurar_log("America/Sao_Paulo", saida)
    registro = logging.LogRecord("essentials", logging.INFO, __file__, 1, "teste", None, None)
    registro.created = 1_767_268_800.0  # 2026-01-01 12:00:00 UTC
    logger.handlers[0].handle(registro)
    assert saida.getvalue() == "[2026-01-01 09:00:00]-[INFO]: teste\n"
    assert FORMATO == "[%(asctime)s]-[%(levelname)s]: %(message)s"
    assert data_hora(1_767_268_800_000, "America/Sao_Paulo") == "2026-01-01 09:00:00"
    assert data_hora(None) == "-"


def linha_log(nivel: str, **campos) -> dict:
    return {"cd_nivel": nivel, "nm_job": "carga", "id_execucao_job": "42", **campos}


def test_log_legivel_conta_a_carga_inteira_e_nunca_leva_campo_fora_da_lista():
    linhas = [
        linha_log("job", nr_ms_inicio=1_767_268_800_000, nr_ms_fim=1_767_269_100_000, ds_duracao="00:05:00",
                  st_execucao="FAILED"),
        linha_log("tabela", nm_tarefa=TAREFA_PIPELINE, nm_schema="portfolio_silver", nm_tabela="silver_agenda",
                  ds_metodo_carga="AUTO CDC FROM SNAPSHOT SCD2", cd_tecnica_refresh="COMPLETE_RECOMPUTE",
                  nr_ms_ultima_anterior=None, nr_ms_inicio=1_767_268_860_000, nr_ms_fim=1_767_268_920_000,
                  ds_duracao="00:01:00", st_execucao="FAILED", qt_linhas_gravadas=234, qt_linhas_descartadas=2,
                  qt_linhas_alerta=30, qt_linhas_tabela=252, ds_motivo_falha="Regra violada: data_plausivel.",
                  # Campo que não é do log legível (ex.: um texto bruto que alguém acrescente).
                  ds_texto_erro="Input record: Maria Souza (41) 99999-0000"),
        linha_log("tarefa", nm_tarefa=TAREFA_PIPELINE, ds_duracao="00:03:10", st_execucao="FAILED",
                  ds_motivo_falha="Regra violada: data_plausivel."),
    ]
    mensagens = mensagens_do_log(linhas, "America/Sao_Paulo")
    texto = "\n".join(mensagem for _, mensagem in mensagens)
    assert mensagens[0] == (logging.INFO, "Início do job carga (execução 42): 2026-01-01 09:00:00")
    assert ("Tabela portfolio_silver.silver_agenda | método: AUTO CDC FROM SNAPSHOT SCD2 | técnica: "
            "COMPLETE_RECOMPUTE | última atualização anterior: - | início: 2026-01-01 09:01:00") in texto
    assert ("status: FAILED | gravadas: 234 | descartadas: 2 | alertas: 30 | total na tabela: 252 | "
            "duração: 00:01:00 | término: 2026-01-01 09:02:00") in texto
    assert (logging.ERROR, "Tarefa processar_medalhao | status: FAILED | duração: 00:03:10") in mensagens
    assert (logging.ERROR, "Falha em processar_medalhao: Regra violada: data_plausivel.") in mensagens
    assert mensagens[-1][1] == "Fim do job carga | status: FAILED | duração: 00:05:00 | término: 2026-01-01 09:05:00"
    assert "Maria" not in texto and "9999" not in texto


# job.yml -------------------------------------------------------------------------------------


def test_publicar_monitoramento_roda_sempre_depois_de_tudo_e_nunca_de_novo():
    publicar = tarefas()[TAREFA_PROPRIA]
    assert publicar["run_if"] == "ALL_DONE"
    assert publicar["max_retries"] == 0
    assert {d["task_key"] for d in publicar["depends_on"]} == {
        "ingerir_fontes_externas", "preparar_governanca", TAREFA_PIPELINE,
    }
    parametros = publicar["spark_python_task"]["parameters"]
    valor = {parametros[i]: parametros[i + 1] for i in range(0, len(parametros), 2)}
    assert valor["--run-id"] == "{{job.run_id}}"
    assert valor["--schema-monitoramento"] == "${resources.schemas.monitoramento.name}"
    assert (RAIZ / "resources" / publicar["spark_python_task"]["python_file"]).resolve().is_file()


def test_pipeline_nunca_roda_com_full_refresh_pelo_job():
    # Um full refresh apagaria o histórico SCD2 e a bronze (que não voltam da landing).
    pipeline = tarefas()[TAREFA_PIPELINE]
    assert pipeline["pipeline_task"] == {"pipeline_id": "${resources.pipelines.essentials_pipeline.id}",
                                         "full_refresh": False}
    assert pipeline["run_if"] == "NONE_FAILED"
    assert {d["task_key"] for d in pipeline["depends_on"]} == {"ingerir_fontes_externas", "preparar_governanca"}


def folhas() -> set[str]:
    com_dependentes = {d["task_key"] for tarefa in job()["tasks"] for d in tarefa.get("depends_on", [])}
    return set(tarefas()) - com_dependentes


def test_aviso_de_falha_sai_logo_depois_da_publicacao_e_o_job_fica_vermelho():
    avisar = tarefas()["avisar_falha"]
    # Depende das tarefas da carga (a falha delas dispara o aviso) e da publicação (o motivo já
    # está gravado quando o alerta roda).
    assert {d["task_key"] for d in avisar["depends_on"]} == {
        "ingerir_fontes_externas", "preparar_governanca", TAREFA_PIPELINE, TAREFA_PROPRIA,
    }
    assert avisar["run_if"] == "AT_LEAST_ONE_FAILED"
    assert avisar["alert_task"] == {"alert_id": "${resources.alerts.falha_carga.id}",
                                    "warehouse_id": "${var.warehouse_id}"}
    # O resultado da execução vem das folhas: se a avisar_falha fosse a folha, a carga com falha
    # terminaria "Succeeded with failures" e o aviso de falha do job não sairia.
    assert folhas() == {"encerrar_com_falha"}
    encerrar = tarefas()["encerrar_com_falha"]
    assert encerrar["depends_on"] == [{"task_key": "avisar_falha"}]
    caminho = encerrar["sql_task"]["file"]["path"].replace("${workspace.file_path}", str(RAIZ))
    assert "raise_error(" in Path(caminho).read_text(encoding="utf-8")


def test_alerta_de_falha_avisa_de_novo_numa_nova_falha():
    # Com retrigger_seconds 0, uma falha no dia seguinte (a de ontem ainda nas 24 horas) não
    # mandaria e-mail nenhum.
    alerta = carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]["falha_carga"]
    assert 0 < alerta["evaluation"]["notification"]["retrigger_seconds"] < 86400


def test_falha_carga_ativo_em_dev_e_pausado_no_ci():
    targets = bundle()["targets"]
    assert "falha_carga" not in targets["dev"]["resources"]["alerts"]
    assert targets["ci"]["resources"]["alerts"]["falha_carga"]["schedule"]["pause_status"] == "PAUSED"
    alerta = carregar_yaml(RAIZ / "resources" / "alertas.yml")["resources"]["alerts"]["falha_carga"]
    assert alerta["evaluation"]["notification"]["subscriptions"] == [{"user_email": "${var.usuario_alerta}"}]


def test_tarefas_python_escrevem_o_log_no_fuso_do_projeto():
    assert bundle()["variables"]["fuso_horario"]["default"] == "America/Sao_Paulo"
    for chave, tarefa in tarefas().items():
        if "spark_python_task" in tarefa:
            parametros = tarefa["spark_python_task"]["parameters"]
            assert parametros[parametros.index("--fuso-horario") + 1] == "${var.fuso_horario}", chave


# Ingestão das fontes externas ----------------------------------------------------------------


def despachante():
    import ingestao.ingerir_fontes_externas as modulo

    return modulo


BANCO = {"nome": "vendas", "tipo": "banco"}
API = {"nome": "precos", "tipo": "api"}


def test_variavel_de_ingestao_reflete_o_fontes_yml():
    # Fonte banco ou api sem a variável em "true": a ingestão é pulada e a carga fica sem dado novo.
    modulo = despachante()
    esperado = "true" if modulo.tem_fonte_externa(FONTES) else "false"
    assert bundle()["variables"]["ingerir_fontes_externas"]["default"] == esperado
    assert modulo.tipos_externos([{"tipo": "arquivo"}, API, BANCO]) == ["banco", "api"]
    assert not modulo.tem_fonte_externa([{"tipo": "arquivo"}, {"tipo": "tabela"}])
    condicao = tarefas()["tem_fonte_externa"]["condition_task"]
    assert condicao == {"op": "EQUAL_TO", "left": "${var.ingerir_fontes_externas}", "right": "true"}
    assert tarefas()["ingerir_fontes_externas"]["depends_on"] == [{"task_key": "tem_fonte_externa", "outcome": "true"}]


def test_um_tipo_com_erro_nao_impede_o_outro_e_a_tarefa_falha_sem_a_mensagem(monkeypatch):
    import essentials.config_fontes
    import ingestao.api_para_landing
    import ingestao.banco_para_landing

    chamados = []

    def banco_com_erro(fontes, landing):
        chamados.append("banco")
        raise ValueError("valor do registro: Maria Souza")

    monkeypatch.setattr(ingestao.banco_para_landing, "ingerir", banco_com_erro)
    monkeypatch.setattr(ingestao.api_para_landing, "ingerir", lambda fontes, landing: chamados.append("api"))
    monkeypatch.setattr(essentials.config_fontes, "carregar_fontes", lambda caminho: [BANCO, API])
    argv = ["x", "--config", "c", "--landing", "/Volumes/l", "--codigo", str(RAIZ / "src"), "--fuso-horario", "UTC"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as saida:
        despachante().main()
    assert chamados == ["banco", "api"]
    assert str(saida.value) == "Ingestão com erro: banco (ValueError). Veja o log da tarefa."
