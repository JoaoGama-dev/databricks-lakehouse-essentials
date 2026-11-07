# 0025. Núcleo e camada do projeto

- **Status:** aceita
- **Data:** 2026-11-07

## Contexto

O pacote Essentials é um acelerador: o motor deve ser o mesmo em todo cliente
([ADR 0007](0007-acelerador-orientado-por-metadados.md)). Na prática, o exemplo da agenda
de entrevistas estava misturado ao motor: testes, painel e documentação citavam fontes,
colunas e regras do exemplo. Num cliente novo, não era claro o que trocar e o que manter.
O pipeline também listava cada arquivo em `libraries`, então todo `silver_<fonte>.sql` ou
`gold_*.sql` novo obrigava a editar um arquivo de recurso.

## Decisão

O pacote tem duas partes, com uma fronteira escrita em
[`docs/padroes/nucleo-e-projeto.md`](../padroes/nucleo-e-projeto.md).

- **Camada do projeto** (muda por cliente): `config/fontes.yml`, `silver_<fonte>.sql`,
  `gold_*.sql`, `gold_vw_*.sql`, os painéis de `src/dashboards/` (menos o de saúde),
  `tests/projeto/` e os valores de variáveis do `databricks.yml`. O exemplo do portfólio
  (`data/`, `scripts/integracao.py`, `integracao.yml`) também é camada do projeto.
- **Núcleo** (igual para todo cliente): todo o resto.
- **O núcleo nunca cita nome de fonte, coluna ou regra de um cliente.** Dois testes em
  `tests/nucleo/` garantem:
  - `test_contrato_do_projeto.py` gera testes do `config/fontes.yml` e da gold de qualquer
    cliente, sem citar nome: chave com `nao_nulo` que barra a linha, coluna sensível com
    máscara ao chegar à gold e função de máscara na view, descrição em toda coluna, bronze
    e silver por fonte, `COMMENT`, propriedades e prefixos na gold. Ele diz o que não
    conseguiu verificar;
  - `test_nucleo_sem_projeto.py` falha se nome de fonte, coluna, regra, tabela gold do
    projeto ou termo de `tests/projeto/termos_do_negocio.py` aparecer no núcleo. Os nomes
    das fontes fictícias do núcleo e os tipos genéricos de máscara são permitidos.
- **O pipeline lê a pasta `src/pipeline/` por `glob`** em `resources/pipeline.yml`
  (Public Preview, validado no dev). Arquivo novo entra sozinho; a pasta só pode ter código
  do pipeline.
- **O painel do cliente é `painel_negocio`** (`src/dashboards/negocio.lvdash.json`, nome
  "Essentials · <projeto> · Negócio"). O de saúde continua no núcleo.
- Os testes do motor usam fontes fictícias próprias (`tests/nucleo/fontes_ficticias.py`).

## Alternativas consideradas

- **Um repositório por cliente, copiando tudo:** é simples no começo, mas cada correção do
  motor teria de ser copiada para N repositórios, e eles se afastariam uns dos outros.
- **Transformar o núcleo em pacote versionado já agora:** resolve a cópia, mas traz custo
  de publicação, versionamento e compatibilidade que não se paga com um cliente. Fica para
  depois (ver Consequências).
- **Só uma convenção na documentação, sem teste:** a fronteira se desfaz na primeira
  pressa. Por isso é teste.

## Consequências

- Num cliente novo, a skill `novo-cliente` troca só a camada do projeto, e os testes de
  `tests/nucleo/` mostram se o contrato foi cumprido.
- O contrato tem limites. A máscara só é reconhecida em `alias.coluna AS nome`; uma
  expressão que deriva de coluna sensível, como `concat`, precisa de revisão humana. O
  vazamento só pega palavra inteira. Os testes não substituem a revisão.
- "Os testes do núcleo passam sem mudar nada" vale se os nomes do cliente não colidirem
  com termos do núcleo e se a gold seguir o formato do contrato.
- A documentação, os agentes, as skills e os hooks ainda citam o exemplo; ficam fora da
  varredura por enquanto.
- O `glob` está em Public Preview. Acompanhe se o recurso mudar.
- **Caminho futuro:** com 3 ou 4 clientes, transformar o núcleo num pacote versionado:
  um wheel instalado pelo `requirements-runtime.txt`, ou um bundle de outro repositório
  trazido por `include`. A fronteira e os testes desta decisão já deixam o corte pronto.
  Até lá, o núcleo fica neste repositório.
