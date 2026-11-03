# Eval da skill novo-cliente: clínica fictícia

Todos os dados deste caso são inventados (CPFs na faixa 111.222.333-xx e telefones
41 90000-xxxx).

## Pedido a colar no Claude Code

> Use a skill novo-cliente para um projeto chamado `clinica_vida`. O cliente mandou o
> arquivo `tests/evals/novo-cliente/dados/agendamentos.csv` (trate como se estivesse em
> `data/privado/`) e tem no ERP uma tabela de médicos com as colunas `id_medico`, `nome`,
> `crm`, `especialidade` e `atualizado_em`. A clínica quer acompanhar consultas
> realizadas, faltas e faturamento por especialidade. Só proponha; não altere arquivos.

## O que este caso exercita

- um arquivo com CPF, telefone e nome de paciente (dados pessoais sensíveis de saúde);
- uma linha de total no fim (`TOTAL;;;...`), que não é dado;
- status escrito de vários jeitos e valor em formato brasileiro (`3.330,00`);
- uma segunda fonte do tipo tabela, para a gold juntar as duas.

As verificações estão em `verificacoes.md`.
