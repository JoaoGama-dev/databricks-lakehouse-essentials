"""Gera agendas de entrevistas FICTÍCIAS no mesmo formato da planilha real do RH.

Formato (igual ao da exportação do Excel):
  - cabeçalho        AGENDA DIA dd/mm/aaaa;NOME;VAGA;TELEFONE;STATUS.;
  - separador do dia AGENDA DIA dd/mm/aaaa;;;;;
  - entrevista       hh:mm;nome;vaga;telefone;status;
  - linhas ";;;;;" no fim, UTF-8 com BOM e quebra de linha CRLF.

Mantém a sujeira da planilha real: status escrito de vários jeitos, ponto final e
espaços no nome, telefones inválidos, linha sem nome, linha sem horário e entrevista
reagendada no mesmo dia. Nomes e telefones são inventados (telefones no padrão
41 90000-xxxx).

Gera duas versões da mesma planilha:
  agenda_exemplo_v1.csv  carga inicial, com algumas entrevistas sem status
  agenda_exemplo_v2.csv  a mesma agenda com esses status preenchidos e mais um dia

Uso:
    python data/gerar_dados_exemplo.py           # grava em data/
    python data/gerar_dados_exemplo.py pasta/    # grava em outra pasta
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

ARQUIVO_V1 = "agenda_exemplo_v1.csv"
ARQUIVO_V2 = "agenda_exemplo_v2.csv"
CODIFICACAO = "utf-8-sig"  # UTF-8 com BOM, como o Excel exporta
QUEBRA_DE_LINHA = "\r\n"
LINHAS_VAZIAS_NO_FIM = 9

PRIMEIROS_NOMES = [
    "Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique",
    "Isabela", "Jonas", "Karina", "Lucas", "Mariana", "Nicolas", "Olívia", "Paulo",
    "Rafaela", "Samuel", "Tatiane", "Vinícius", "Yasmin", "André", "Beatriz",
    "Caio", "Daniela", "Emerson", "Fernanda", "Gustavo", "Helena", "Igor",
]
SOBRENOMES = [
    "Almeida", "Barbosa", "Cardoso", "Dias", "Esteves", "Ferreira", "Gomes",
    "Hoffmann", "Lima", "Moreira", "Nogueira", "Oliveira", "Pereira", "Rocha",
    "Santos", "Teixeira",
]
VAGAS = [
    "Cozinheiro", "Cozinheira", "Atendente Barigui", "Atendente Atuba", "Atendente Jockey",
    "Auxiliar administrativo São José", "Auxiliar adminidtrativo", "Auxiliar de limpeza Juveve",
    "Estoquista", "Vendedora ótica", "Frentista", "Garçom Barigui", "Confeiteira",
    "Auxiliar de cozinha cafeteria", "Recepcionista Araucária", "Assistente financeiro",
    "Nail designer", "Auxiliar de loja", "Corretora",
]
HORARIOS = [f"{h:02d}:{m:02d}" for h in (9, 10, 11, 13, 14, 15, 16) for m in (0, 15, 30, 45)]

# Variações de escrita encontradas na planilha real, agrupadas pelo status padronizado.
VARIACOES_STATUS = {
    "Aprovado": ["Aprovado", "Aprovada", "aprovado", "APROVADO", " Aprovada "],
    "Reprovado": ["Reprovado", "Reprovada", "reprovado"],
    "Não atendeu": ["N/ atendeu", "N/atendeu"],
    "Cancelado": ["Cancelou", "cancelou"],
    "Pendente": [""],
    "Desconhecido": ["Talvez"],
}
PESOS_STATUS = {
    "Aprovado": 55, "Reprovado": 15, "Não atendeu": 14, "Cancelado": 6, "Pendente": 8, "Desconhecido": 2,
}
STATUS_FINAIS = ["Aprovado", "Reprovado", "Não atendeu"]


def dias_uteis(inicio: date, fim: date) -> list[date]:
    dias = []
    dia = inicio
    while dia <= fim:
        if dia.weekday() < 5:
            dias.append(dia)
        dia += timedelta(days=1)
    return dias


def escrever_status(status: str, rng: random.Random) -> str:
    return rng.choice(VARIACOES_STATUS[status])


def sujar_nome(nome: str, rng: random.Random) -> str:
    sorteio = rng.random()
    if sorteio < 0.06:
        return f"{nome}."
    if sorteio < 0.12:
        return f"{nome} "
    if sorteio < 0.16:
        return nome.upper()
    if sorteio < 0.19:
        return nome.replace(" ", "  ", 1)
    return nome


def gerar_telefone(rng: random.Random) -> str:
    final = f"{rng.randint(0, 9999):04d}"
    sorteio = rng.random()
    if sorteio < 0.03:
        return "4,19E+10"  # número que o Excel converteu para notação científica
    if sorteio < 0.06:
        return f"90000{final}"[:7]  # sem DDD e incompleto
    if sorteio < 0.09:
        return ""
    if sorteio < 0.15:
        return f"41 90000-{final}"
    return f"4190000{final}"


def montar_agenda(dias: list[date], nomes, rng: random.Random, chance_de_agenda: float = 0.5) -> list[dict]:
    """Entrevistas já com a sujeira de digitação, para ficarem iguais nas duas versões."""
    entrevistas = []
    for dia in dias:
        if rng.random() >= chance_de_agenda:
            continue  # nem todo dia tem agenda
        for horario in sorted(rng.sample(HORARIOS, rng.randint(3, 7))):
            entrevistas.append({
                "dia": dia,
                "horario": horario,
                "nome": sujar_nome(next(nomes), rng),
                "vaga": rng.choice(VAGAS),
                "telefone": gerar_telefone(rng),
                "status": escrever_status(rng.choices(list(PESOS_STATUS), list(PESOS_STATUS.values()))[0], rng),
            })
    return entrevistas


def casos_especiais(entrevistas: list[dict], nomes, rng: random.Random) -> None:
    """Acrescenta os defeitos que a silver precisa tratar, num dia que já tem agenda."""
    dia = entrevistas[len(entrevistas) // 2]["dia"]
    reagendado = next(nomes)
    entrevistas.extend([
        # Mesma pessoa duas vezes no mesmo dia: vale a linha mais abaixo.
        {"dia": dia, "horario": "08:00", "nome": reagendado, "vaga": "Estoquista",
         "telefone": gerar_telefone(rng), "status": "Reagendado"},
        {"dia": dia, "horario": "17:30", "nome": reagendado, "vaga": "Estoquista",
         "telefone": gerar_telefone(rng), "status": "Aprovado"},
        # Sem nome: descartada pela regra nome_preenchido.
        {"dia": dia, "horario": "17:45", "nome": "", "vaga": "Auxiliar de produção Piraquara",
         "telefone": gerar_telefone(rng), "status": "N/ atendeu"},
        # Sem horário e sem nome, como acontece no fim de alguns dias da planilha.
        {"dia": dia, "horario": "", "nome": "", "vaga": "Auxiliar de produção Piraquara",
         "telefone": gerar_telefone(rng), "status": "Aprovado"},
        # Sem horário, com nome: entra com alerta horario_valido.
        {"dia": dia, "horario": "", "nome": next(nomes), "vaga": "Frentista",
         "telefone": gerar_telefone(rng), "status": "Aprovada"},
    ])
    entrevistas.sort(key=lambda e: (e["dia"], e["horario"] == "", e["horario"]))


def linhas_da_planilha(entrevistas: list[dict], rng: random.Random) -> list[str]:
    primeiro_dia = entrevistas[0]["dia"]
    linhas = [f"AGENDA DIA {primeiro_dia:%d/%m/%Y};NOME;VAGA;TELEFONE;STATUS.;"]
    dia_atual = None
    for entrevista in entrevistas:
        if entrevista["dia"] != dia_atual:
            dia_atual = entrevista["dia"]
            rotulo = "AGENDA DIa" if rng.random() < 0.15 else "AGENDA DIA"  # erro de digitação real
            linhas.append(f"{rotulo} {dia_atual:%d/%m/%Y};;;;;")
        campos = [entrevista[c] for c in ("horario", "nome", "vaga", "telefone", "status")]
        linhas.append(";".join(campos) + ";")
    linhas.extend([";;;;;"] * LINHAS_VAZIAS_NO_FIM)
    return linhas


def gravar(caminho: Path, linhas: list[str]) -> None:
    with caminho.open("w", encoding=CODIFICACAO, newline="") as arquivo:
        arquivo.write(QUEBRA_DE_LINHA.join(linhas) + QUEBRA_DE_LINHA)


def gerar(pasta_saida: Path, semente: int = 42) -> list[Path]:
    rng = random.Random(semente)
    todos_os_nomes = [f"{p} {s}" for p in PRIMEIROS_NOMES for s in SOBRENOMES]
    rng.shuffle(todos_os_nomes)
    nomes = iter(todos_os_nomes)

    v1 = montar_agenda(dias_uteis(date(2025, 8, 4), date(2025, 11, 28)), nomes, rng)
    casos_especiais(v1, nomes, rng)

    # v2: a planilha é reenviada inteira, com os status vazios preenchidos e mais um dia.
    v2 = [
        {**e, "status": escrever_status(rng.choice(STATUS_FINAIS), rng)} if e["status"] == "" and e["nome"] else e
        for e in v1
    ]
    v2 += montar_agenda(dias_uteis(date(2025, 12, 1), date(2025, 12, 1)), nomes, rng, chance_de_agenda=1.0)

    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminhos = [pasta_saida / ARQUIVO_V1, pasta_saida / ARQUIVO_V2]
    for caminho, entrevistas in zip(caminhos, (v1, v2), strict=True):
        gravar(caminho, linhas_da_planilha(entrevistas, random.Random(semente)))
    return caminhos


if __name__ == "__main__":
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    for caminho in gerar(pasta):
        print(f"Arquivo gerado: {caminho}")
