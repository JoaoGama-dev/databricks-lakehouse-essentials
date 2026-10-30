-- Camada gold: entrevistas com a área do cargo (junção agenda x cargos) e indicadores.

-- Cada entrevista recebe a área do cargo cujo prefixo combina com o nome da vaga.
-- Quando mais de um prefixo combina, vale o mais longo (o mais específico):
-- "auxiliar de cozinha" ganha de "auxiliar".
CREATE OR REFRESH MATERIALIZED VIEW gold_entrevistas
COMMENT 'Situação atual de cada entrevista com a área do cargo e indicadores de comparecimento, aprovação e retorno pendente. Vagas sem prefixo cadastrado ficam como Não classificada.'
TBLPROPERTIES ('camada' = 'gold')
AS SELECT
  e.data_entrevista,
  trunc(e.data_entrevista, 'MM') AS mes_entrevista,
  e.horario,
  e.nome_candidato,
  e.vaga,
  coalesce(c.area, 'Não classificada') AS area,
  e.status,
  e.telefone,
  e.status IN ('Aprovado', 'Reprovado') AS compareceu,
  e.status = 'Aprovado' AS aprovado,
  -- A entrevista já passou e ninguém registrou o resultado.
  e.status = 'Pendente' AND e.data_entrevista < current_date() AS sem_retorno
FROM silver_agenda AS e
LEFT JOIN silver_cargos AS c
  ON lower(e.vaga) LIKE concat(c.prefixo_vaga, '%')
QUALIFY row_number() OVER (
  PARTITION BY e.data_entrevista, e.nome_candidato
  ORDER BY length(c.prefixo_vaga) DESC NULLS LAST
) = 1;

-- Indicadores mensais por área e status, base dos gráficos do painel.
CREATE OR REFRESH MATERIALIZED VIEW gold_indicadores_entrevistas
COMMENT 'Total de entrevistas por mês, área e status, com comparecimentos, aprovações e entrevistas sem retorno.'
TBLPROPERTIES ('camada' = 'gold')
AS SELECT
  mes_entrevista,
  area,
  status,
  count(*) AS total_entrevistas,
  count_if(compareceu) AS total_compareceram,
  count_if(aprovado) AS total_aprovados,
  count_if(sem_retorno) AS total_sem_retorno
FROM gold_entrevistas
GROUP BY mes_entrevista, area, status;
