"""Totais esperados depois de cada rodada no target ci, com os dados fictícios do gerador.

O gerador (data/gerar_dados_exemplo.py) usa semente fixa, então os totais são sempre os
mesmos. Se o gerador, o fontes.yml ou a silver da agenda mudarem, estes números mudam:
rode o workflow de integração, confira a diferença e atualize aqui no mesmo PR.

Rodada 1: a agenda v1. Rodada 2: numa carga só, a v2 (a v1 com os status vazios preenchidos
e mais um dia), a v6 (a v1 chegando atrasada), a v7 (só o cabeçalho) e a v5 (os bytes da v2
com outro nome, enviada por último). O retrato é a v5: empata com a v2 na data de referência
e ganha no desempate; a silver (SCD tipo 2) fecha as versões das entrevistas que mudaram.

  linhas_retrato  linhas do retrato antes das regras drop (aprovadas + descartadas)
  vigentes        versões abertas da silver (__END_AT vazio): uma por entrevista
  versoes         todas as versões da silver
  fechadas        versões fechadas (__END_AT preenchido)
  arquivos_bronze arquivos distintos na bronze depois da rodada
  retrato         arquivo das versões vigentes da silver (o retrato é privado do pipeline)
  ignorados       arquivos da carga que não viraram o retrato (mon_estrutura, arquivo_ignorado)
"""

ESPERADO = {
    1: {
        "linhas_retrato": 229,
        "vigentes": 227,
        "versoes": 227,
        "fechadas": 0,
        "descartes": {"nome_preenchido": 2, "data_entrevista_valida": 0},
        "alertas": {"status_conhecido": 9, "telefone_valido": 18, "horario_valido": 2},
        "arquivos_bronze": 1,
        "retrato": {"agenda_exemplo_v1.csv"},
        "ignorados": set(),
    },
    # v2 = v1 + 7 entrevistas do dia novo (1 com telefone inválido); as 18 entrevistas que
    # tinham status vazio mudam e ganham uma versão nova na silver.
    2: {
        "linhas_retrato": 236,
        "vigentes": 234,
        "versoes": 252,
        "fechadas": 18,
        "descartes": {"nome_preenchido": 2, "data_entrevista_valida": 0},
        "alertas": {"status_conhecido": 9, "telefone_valido": 19, "horario_valido": 2},
        "arquivos_bronze": 5,
        "retrato": {"agenda_exemplo_v5.csv"},
        "ignorados": {"agenda_exemplo_v2.csv", "agenda_exemplo_v6.csv", "agenda_exemplo_v7.csv"},
    },
}
