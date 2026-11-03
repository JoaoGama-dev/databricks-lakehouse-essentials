# Eval da skill nova-fonte: admissões fictícias

Todos os dados deste caso são inventados (CPFs na faixa 222.333.444-xx).

## Pedido a colar no Claude Code

> Use a skill nova-fonte para incluir no projeto portfolio a fonte de admissões, que o RH
> vai mandar por arquivo como `tests/evals/nova-fonte/dados/admissoes.csv` (trate como se
> estivesse em `data/privado/`). Cada arquivo traz só as admissões novas da semana.
> Queremos saber quantos candidatos aprovados na entrevista foram de fato admitidos.
> Só proponha; não altere arquivos.

## O que este caso exercita

- carga incremental (cada arquivo traz só o que é novo);
- CPF e nome de colaborador (dados pessoais);
- salário em formato brasileiro entre aspas (`"3.200,50"`) e datas em `yyyy-MM-dd`;
- status com variações e um CPF vazio;
- junção com a agenda de entrevistas já existente (nome + vaga), que é frágil.

As verificações estão em `verificacoes.md`.
