-- Camada gold em modelo estrela: dimensão de cargos, fato de entrevistas e agregada mensal.
-- Padrão de nomes: gold_<tipo>_<nome> (dim, fato, agg) e colunas com prefixo da classe da
-- informação (id_, nm_, dt_, st_, fl_, qt_...), como na silver.
-- Dicionário de dados: toda coluna é declarada com tipo e COMMENT, na ordem do SELECT.

-- Dimensão de cargos. O membro id_cargo = -1 ("Não classificada") recebe as entrevistas
-- cuja vaga não combina com nenhum prefixo cadastrado, para a fato nunca ficar sem cargo.
CREATE OR REFRESH MATERIALIZED VIEW gold_dim_cargo (
  id_cargo BIGINT COMMENT 'Identificador do cargo; -1 é o membro Não classificada.',
  ds_prefixo_vaga STRING COMMENT 'Começo do nome da vaga, em minúsculas, que identifica o cargo.',
  nm_area STRING COMMENT 'Área da empresa à qual o cargo pertence.',
  dh_atualizacao TIMESTAMP COMMENT 'Data e hora da última alteração do cargo no cadastro de origem.'
)
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
CREATE OR REFRESH MATERIALIZED VIEW gold_fato_entrevista (
  dt_entrevista DATE COMMENT 'Data da entrevista.',
  dt_mes_entrevista DATE COMMENT 'Primeiro dia do mês da entrevista, para agrupar por mês.',
  hr_entrevista STRING COMMENT 'Horário da entrevista no formato HH:mm.',
  nm_candidato STRING COMMENT 'Nome do candidato.',
  nm_vaga STRING COMMENT 'Nome da vaga como escrito na agenda.',
  id_cargo BIGINT COMMENT 'Cargo da vaga (chave para gold_dim_cargo); -1 quando a vaga não tem prefixo cadastrado.',
  st_entrevista STRING COMMENT 'Resultado da entrevista padronizado (Aprovado, Reprovado, Não atendeu, Cancelado, Reagendado, Pendente).',
  st_situacao STRING COMMENT 'Situação para acompanhamento: Concluído, Em andamento, Pendente ou Não identificado.',
  nr_telefone STRING COMMENT 'Telefone do candidato mascarado por LGPD (DDD e 4 últimos dígitos).',
  fl_compareceu BOOLEAN COMMENT 'Verdadeiro quando o candidato compareceu (Aprovado ou Reprovado).',
  fl_aprovado BOOLEAN COMMENT 'Verdadeiro quando o candidato foi aprovado.',
  fl_sem_retorno BOOLEAN COMMENT 'Verdadeiro quando a entrevista já passou e o resultado não foi registrado.'
)
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
  -- Situação para acompanhamento: o que foi concluído, o que está em andamento e o que
  -- está pendente. Status fora da lista de-para fica como Não identificado.
  CASE
    WHEN e.st_entrevista IN ('Aprovado', 'Reprovado', 'Não atendeu', 'Cancelado') THEN 'Concluído'
    WHEN e.st_entrevista = 'Reagendado' THEN 'Em andamento'
    WHEN e.st_entrevista = 'Pendente' THEN 'Pendente'
    ELSE 'Não identificado'
  END AS st_situacao,
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

-- Agregada mensal por área, situação e status, base dos gráficos do painel.
CREATE OR REFRESH MATERIALIZED VIEW gold_agg_entrevista_mensal (
  dt_mes_entrevista DATE COMMENT 'Primeiro dia do mês das entrevistas.',
  nm_area STRING COMMENT 'Área da empresa (Não classificada quando a vaga não tem cargo cadastrado).',
  st_situacao STRING COMMENT 'Situação para acompanhamento: Concluído, Em andamento, Pendente ou Não identificado.',
  st_entrevista STRING COMMENT 'Resultado da entrevista padronizado.',
  qt_entrevistas BIGINT COMMENT 'Quantidade de entrevistas.',
  qt_compareceram BIGINT COMMENT 'Quantidade de entrevistas em que o candidato compareceu.',
  qt_aprovados BIGINT COMMENT 'Quantidade de candidatos aprovados.',
  qt_sem_retorno BIGINT COMMENT 'Quantidade de entrevistas que já passaram sem resultado registrado.'
)
COMMENT 'Entrevistas por mês, área, situação e status, com comparecimentos, aprovações e entrevistas sem retorno.'
TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'agregada')
AS SELECT
  f.dt_mes_entrevista,
  d.nm_area,
  f.st_situacao,
  f.st_entrevista,
  count(*) AS qt_entrevistas,
  count_if(f.fl_compareceu) AS qt_compareceram,
  count_if(f.fl_aprovado) AS qt_aprovados,
  count_if(f.fl_sem_retorno) AS qt_sem_retorno
FROM gold_fato_entrevista AS f
JOIN gold_dim_cargo AS d
  ON f.id_cargo = d.id_cargo
GROUP BY f.dt_mes_entrevista, d.nm_area, f.st_situacao, f.st_entrevista;
