"""Termos de negócio do exemplo que nunca podem aparecer no núcleo.

Camada do projeto: cada cliente troca esta lista pelos termos do negócio dele. Os nomes de
fonte, coluna, regra e tabela da gold já são lidos sozinhos do config/fontes.yml e da gold por
tests/nucleo/test_nucleo_sem_projeto.py; aqui ficam só as palavras do assunto do cliente.
"""

TERMOS_DO_NEGOCIO = (
    "agenda",
    "agendas",
    "entrevista",
    "entrevistas",
    "candidato",
    "candidatos",
    "candidata",
    "vaga",
    "vagas",
)
