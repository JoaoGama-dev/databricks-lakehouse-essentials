# Padrão de nomes

Vale para todos os projetos do pacote Essentials. Os testes (`tests/test_projeto.py`) e a
validação do `config/fontes.yml` recusam o que fugir dele.

## Estrutura no Unity Catalog

- Catálogo `essentials` (dev) ou o catálogo do cliente (prod).
- Um schema por camada, criados pelo bundle (`resources/governanca.yml`,
  [ADR 0018](../adr/0018-schemas-por-camada.md)):

  | Schema | O que tem | Quem acessa |
  | --- | --- | --- |
  | `<projeto>_bronze` | `bronze_<fonte>` e o volume `landing` | engenharia |
  | `<projeto>_silver` | `silver_<fonte>` e a função `mascarar_dado_pessoal` | engenharia |
  | `<projeto>_gold` | `gold_fato_*`, `gold_dim_*` e `gold_vw_*` | engenharia e leitura do negócio |
  | `<projeto>_monitoramento` | event log `mon_log_eventos`, a tabela `mon_log_execucao` e as views `mon_*` (inclusive `mon_falhas`) | engenharia |

  Em dev o bundle prefixa os quatro com `dev_<usuário>_`, para cada pessoa ter o seu.
- Não há schema de origem: o catálogo `essentials` é o único que o `setup/` cria.
- Bundle `essentials_<projeto>`; job `<projeto>_job_carga_diaria`; pipeline
  `<projeto>_pipeline_medalhao`. As chaves internas no bundle (`essentials_carga_diaria`,
  `essentials_pipeline`) não mudam: trocá-las recriaria os recursos. Nada com o nome do
  projeto escrito fixo no código: use `${var.projeto}` no bundle ou o marcador
  `{projeto}` no `fontes.yml`.

## Tabelas: `camada_tipo_nome`

| Prefixo | Tipo (`TBLPROPERTIES 'tipo'`) | Exemplo |
| --- | --- | --- |
| `bronze_<fonte>` | `bruta` | `bronze_agenda` |
| `silver_int_<fonte>_<passo>` | `intermediaria` | `silver_int_agenda_retrato` (privada do pipeline), `silver_int_agenda_preparada` (view temporária) |
| `silver_<fonte>` | `atual` (estado atual) ou `historico` (SCD tipo 2, com `historico: true`) | `silver_agenda` |
| `gold_dim_<nome>` | `dimensao` | (o exemplo não tem) |
| `gold_fato_<nome>` | `fato` | `gold_fato_entrevista` |
| `gold_agg_<nome>` | `agregada` | (o exemplo não tem; o painel calcula) |
| `gold_vw_<nome>` | `view` | `gold_vw_entrevistas` |
| `mon_<nome>` | `qualidade`, `atualizacao`, `custo`, `volume`, `estrutura`, `execucoes`, `falha`, `observabilidade` | `mon_qualidade_diaria`; `mon_log_execucao` (tipo `observabilidade`) |

- Fato e dimensão no singular; `gold_vw_*` no plural do que mostra, como a view do painel.
- Não existe `silver_<fonte>_historico`: com histórico, a própria `silver_<fonte>` é a SCD
  tipo 2 ([ADR 0019](../adr/0019-silver-unica-scd2-com-retrato-privado.md)).
- `gold_vw_*` são views da gold escritas em `src/views/gold_vw_<nome>.sql` e criadas pela
  tarefa `publicar_monitoramento`, com `COMMENT` em cada coluna.
- `mon_*` são as views de monitoramento (camada `monitoramento`), criadas pela tarefa
  `publicar_monitoramento` a partir de `src/essentials/monitoramento_sql.py`; o event log
  publicado do pipeline é `mon_log_eventos`. Ficam no schema `<projeto>_monitoramento`
  (ADR 0003 e 0021).
- `mon_log_execucao` é a **tabela** do log da carga, de tipo `observabilidade`, criada pela
  `preparar_governanca` com `COMMENT` em cada coluna (ADR 0022). `mon_falhas` é uma view
  sobre ela (a tabela antiga de mesmo nome vira `mon_falhas_legado`).
- Toda tabela e view publicada com `COMMENT` e `TBLPROPERTIES ('camada' = ..., 'tipo' = ...)`;
  os tipos válidos estão em `TIPOS_DE_TABELA` (`src/essentials/config_fontes.py`), que além
  dos da tabela acima aceita `observabilidade`, hoje usado só por `mon_log_execucao`. A tarefa
  `publicar_monitoramento` copia `camada` e `tipo` para as **tags do Unity Catalog** de mesmo nome,
  que dá para filtrar no Catalog Explorer. A fonte da verdade são as `TBLPROPERTIES`.

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
- Colunas técnicas começam com `_` (`_fonte`, `_arquivo_origem`, `_modificado_em`,
  `_ingerido_em`).
- A tabela e os tipos aceitos estão em `PREFIXOS_POR_TIPO` (`src/essentials/config_fontes.py`).
