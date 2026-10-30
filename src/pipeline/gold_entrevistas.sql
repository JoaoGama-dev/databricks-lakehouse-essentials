-- Camada gold em modelo estrela: dimensão de cargos, fato de entrevistas e agregada mensal.
-- Padrão de nomes: gold_<tipo>_<nome> (dim, fato, agg) e colunas com prefixo da classe da
-- informação (id_, nm_, dt_, st_, fl_, qt_...), como na silver.

-- Dimensão de cargos. O membro id_cargo = -1 ("Não classificada") recebe as entrevistas
-- cuja vaga não combina com nenhum prefixo cadastrado, para a fato nunca ficar sem cargo.
CREATE OR REFRESH MATERIALIZED VIEW gold_dim_cargo
COMMENT 'Dimensão de cargos: prefixo do nome da vaga e área. O id_cargo -1 é o membro Não classificada.'
TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'dimensao')
AS SELECT
  id_cargo,
  ds_prefixo_vaga,
  nm_area,
  dh_atualizacao
FROM silver_cargos
UNION ALL
SELECT
  -1,
  CAST(NULL AS STRING),
  'Não classificada',
  CAST(NULL AS TIMESTAMP);

-- Fato de entrevistas: uma linha por entrevista, no estado atual. O cargo é o de prefixo
-- mais longo que combina com o nome da vaga ("auxiliar de cozinha" ganha de "auxiliar").
CREATE OR REFRESH MATERIALIZED VIEW gold_fato_entrevista
COMMENT 'Fato de entrevistas: uma linha por entrevista no estado atual, com o cargo (id_cargo) e as flags de comparecimento, aprovação e retorno pendente.'
TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'fato')
AS SELECT
  e.dt_entrevista,
  trunc(e.dt_entrevista, 'MM') AS dt_mes_entrevista,
  e.hr_entrevista,
  e.nm_candidato,
  e.nm_vaga,
  coalesce(c.id_cargo, -1) AS id_cargo,
  e.st_entrevista,
  e.nr_telefone,
  e.st_entrevista IN ('Aprovado', 'Reprovado') AS fl_compareceu,
  e.st_entrevista = 'Aprovado' AS fl_aprovado,
  -- A entrevista já passou e ninguém registrou o resultado.
  e.st_entrevista = 'Pendente' AND e.dt_entrevista < current_date() AS fl_sem_retorno
FROM silver_agenda AS e
LEFT JOIN silver_cargos AS c
  ON lower(e.nm_vaga) LIKE concat(c.ds_prefixo_vaga, '%')
QUALIFY row_number() OVER (
  PARTITION BY e.dt_entrevista, e.nm_candidato
  ORDER BY length(c.ds_prefixo_vaga) DESC NULLS LAST
) = 1;

-- Agregada mensal por área e status, base dos gráficos do painel.
CREATE OR REFRESH MATERIALIZED VIEW gold_agg_entrevista_mensal
COMMENT 'Entrevistas por mês, área e status, com comparecimentos, aprovações e entrevistas sem retorno.'
TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'agregada')
AS SELECT
  f.dt_mes_entrevista,
  d.nm_area,
  f.st_entrevista,
  count(*) AS qt_entrevistas,
  count_if(f.fl_compareceu) AS qt_compareceram,
  count_if(f.fl_aprovado) AS qt_aprovados,
  count_if(f.fl_sem_retorno) AS qt_sem_retorno
FROM gold_fato_entrevista AS f
JOIN gold_dim_cargo AS d
  ON f.id_cargo = d.id_cargo
GROUP BY f.dt_mes_entrevista, d.nm_area, f.st_entrevista;
