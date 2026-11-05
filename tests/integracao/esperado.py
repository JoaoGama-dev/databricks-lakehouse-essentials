"""Totais esperados depois de cada carga no target ci, com os dados fictícios do gerador.

O gerador (data/gerar_dados_exemplo.py) usa semente fixa, então os totais são sempre os
mesmos. Se o gerador, o fontes.yml ou a silver da agenda mudarem, estes números mudam:
rode o workflow de integração, confira a diferença e atualize aqui no mesmo PR.

Versão 1: carga inicial. Versão 2: a mesma agenda com os status vazios preenchidos e mais
um dia; a silver (SCD tipo 2) fecha as versões antigas das entrevistas que mudaram.

  linhas_retrato  linhas do retrato antes das regras drop (aprovadas + descartadas)
  vigentes        versões abertas da silver (__END_AT vazio): uma por entrevista
  versoes         todas as versões da silver
  fechadas        versões fechadas (__END_AT preenchido)
"""

ESPERADO = {
    1: {
        "linhas_retrato": 229,
        "vigentes": 227,
        "versoes": 227,
        "fechadas": 0,
        "descartes": {"nome_preenchido": 2, "data_entrevista_valida": 0},
        "alertas": {"status_conhecido": 9, "telefone_valido": 18, "horario_valido": 2},
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
    },
}
