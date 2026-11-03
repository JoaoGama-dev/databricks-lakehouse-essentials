# Padrão de nomes

Vale para todos os projetos do pacote Essentials. Os testes (`tests/test_projeto.py`) e a
validação do `config/fontes.yml` recusam o que fugir dele.

## Estrutura no Unity Catalog

- Catálogo `essentials` (dev) ou o catálogo do cliente (prod).
- Um schema por projeto: `<projeto>`, com o volume `landing`; e `<projeto>_origem` para
  sistemas de origem simulados no Free Edition.
- Bundle `essentials_<projeto>`; job `essentials_<projeto>_carga_diaria`; pipeline
  `essentials_<projeto>`. Nada com o nome do projeto escrito fixo no código: use
  `${var.projeto}` no bundle ou o marcador `{projeto}` no `fontes.yml`.

## Tabelas: `camada_tipo_nome`

| Prefixo | Tipo (`TBLPROPERTIES 'tipo'`) | Exemplo |
| --- | --- | --- |
| `bronze_<fonte>` | `bruta` | `bronze_agenda` |
| `silver_int_<fonte>_<passo>` | `intermediaria` | `silver_int_agenda_retrato`, `silver_int_agenda_preparada` |
| `silver_<fonte>` | `atual` | `silver_agenda` |
| `silver_<fonte>_historico` | `historico` | `silver_agenda_historico` |
| `gold_dim_<nome>` | `dimensao` | `gold_dim_cargo` |
| `gold_fato_<nome>` | `fato` | `gold_fato_entrevista` |
| `gold_agg_<nome>` | `agregada` | `gold_agg_entrevista_mensal` |

- Fato e dimensão no singular.
- Toda tabela com `COMMENT` e `TBLPROPERTIES ('camada' = ..., 'tipo' = ...)`; os tipos
  válidos estão em `TIPOS_DE_TABELA` (`src/essentials/config_fontes.py`).

## Colunas: prefixo da classe da informação

| Prefixo | Tipos aceitos | Uso |
| --- | --- | --- |
| `id_` | inteiro, texto | identificador |
| `cd_` | texto, inteiro | código |
| `nm_` | texto | nome |
| `ds_` | texto | descrição |
| `sg_` | texto | sigla |
| `st_` | texto | status ou situação |
| `nr_` | texto, inteiro | número (telefone, documento) |
| `qt_` | inteiro, decimal | quantidade |
| `vl_` | decimal, inteiro | valor |
| `pc_` | decimal | percentual |
| `dt_` | data | data |
| `dh_` | timestamp | data e hora |
| `hr_` | texto | hora (hh:mm) |
| `fl_` | booleano | flag |

- Vale para silver e gold. A bronze e as views de preparação mantêm os nomes da origem.
- Colunas técnicas começam com `_` (`_fonte`, `_arquivo_origem`, `_ingerido_em`).
- A tabela e os tipos aceitos estão em `PREFIXOS_POR_TIPO` (`src/essentials/config_fontes.py`).
