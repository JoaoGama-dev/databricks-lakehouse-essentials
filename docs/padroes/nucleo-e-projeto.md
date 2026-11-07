# Núcleo e camada do projeto

O pacote tem duas partes. O **núcleo** é o motor: o mesmo em todo cliente. A **camada do
projeto** é o que muda de um cliente para outro.

## A regra

**O núcleo nunca contém nome de fonte, coluna ou regra de negócio de um cliente.** Nem em
código, nem em comentário, nem em teste. O que é do cliente vai para a camada do projeto.

Um teste confere: `tests/nucleo/test_nucleo_sem_projeto.py`.

## Camada do projeto

| O quê | Onde |
| --- | --- |
| Fontes, colunas e regras | `config/fontes.yml` |
| Preparação de uma fonte | `src/pipeline/silver_<fonte>.sql` |
| Gold | `src/pipeline/gold_*.sql` |
| Views da gold | `src/views/gold_vw_*.sql` |
| Painel do negócio | `src/dashboards/negocio.lvdash.json` (todos os painéis, menos o de saúde) |
| Valores das variáveis | `variables` e `targets` do `databricks.yml` |
| Testes das regras de negócio | `tests/projeto/` |
| Termos do negócio que o núcleo não pode citar | `tests/projeto/termos_do_negocio.py` |

O exemplo do portfólio (a agenda de entrevistas fictícia) também é camada do projeto. É o
"cliente" de demonstração:

- `data/` (as agendas fictícias e `data/gerar_dados_exemplo.py`);
- `scripts/integracao.py` e `.github/workflows/integracao.yml`, que carregam o exemplo no
  target `ci`;
- `tests/projeto/integracao/`.

## Núcleo

Todo o resto. O principal:

| O quê | Onde |
| --- | --- |
| Lógica da config, monitoramento, log e governança | `src/essentials/` |
| Bronze e silver genéricas | `src/pipeline/bronze.py`, `src/pipeline/silver.py` |
| Ingestão de banco e API | `src/ingestao/` |
| Tarefas de governança e monitoramento | `src/governanca/` |
| Painel de saúde | `src/dashboards/saude.lvdash.json` |
| Formato do `fontes.yml` | `config/fontes.schema.json` |
| Recursos do bundle | `resources/*.yml` e a estrutura do `databricks.yml` |
| Scripts | `scripts/` (menos `integracao.py`) |
| Setup do Free Edition | `setup/` |
| CI e deploy | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |
| Testes do motor e do repositório | `tests/nucleo/`, `tests/conftest.py` |
| Guardrails, agentes e skills | `.claude/` |
| Documentação | `docs/`, `README.md`, `CHANGELOG.md`, `CLAUDE.md` |

O código-fonte do pipeline é a pasta `src/pipeline/` inteira (`glob` em
`resources/pipeline.yml`). Por isso, um arquivo de gold ou de preparação novo entra sozinho,
sem mudar o núcleo. O painel do negócio tem a chave `painel_negocio` em todo projeto.

### Ainda citam o exemplo

O teste varre o código do núcleo. Ficam de fora, por enquanto:

- a documentação, os agentes e as skills: explicam o exemplo e serão revistos;
- os hooks (`.claude/hooks/`), o teste deles e as configurações do repositório
  (`.gitignore`, `.gitattributes`, `.pre-commit-config.yaml`): liberam por nome os arquivos
  fictícios de `data/`.

## Testes

| Pasta | O que testa | Lê o `fontes.yml` do projeto? |
| --- | --- | --- |
| `tests/nucleo/` | o motor, com fontes fictícias e genéricas (`tests/nucleo/fontes_ficticias.py`), o bundle e as proteções do repositório | não |
| `tests/nucleo/test_contrato_do_projeto.py` | o contrato que todo projeto cumpre, gerado do `fontes.yml` e da gold: chave com `nao_nulo` que barra a linha, máscara na gold de toda coluna sensível, descrição em toda coluna, bronze e silver de cada fonte, padrão de nomes e dicionário da gold | sim, sem citar nenhum nome |
| `tests/nucleo/test_nucleo_sem_projeto.py` | que nenhum nome do projeto aparece no núcleo | sim, só para tirar os nomes |
| `tests/projeto/` | as regras de negócio do cliente: limpeza das colunas dele, preparação, gold, view, painel do negócio e o gerador de dados | sim |
| `tests/projeto/integracao/` | os dados no target `ci`, depois da carga do exemplo (marcador `integracao`) | sim |

Num cliente novo, os testes do núcleo passam sem mudar nada. Os de `tests/projeto/` são
reescritos com as regras do cliente.
