-- Camada gold: fato de entrevistas. A view gold_vw_entrevistas (src/views/), lida pelo
-- painel, acrescenta os campos que dependem da data de hoje.
-- Padrão de nomes: gold_<tipo>_<nome> e colunas com prefixo da classe da informação
-- (nm_, dt_, st_, fl_...), como na silver.
-- Dicionário de dados: toda coluna é declarada com tipo e COMMENT, na ordem do SELECT.
-- A gold vai para o schema gold (${schema_gold}), o único com leitura para o negócio
-- (docs/adr/0001-modelo-de-acesso-no-unity-catalog.md); a silver é o schema padrão do
-- pipeline. Colunas com dado pessoal (sensivel: true no fontes.yml) declaram a máscara de
-- coluna (MASK), criada pela tarefa governanca_antes (docs/adr/0002).
-- Sem função não determinística (current_date, current_timestamp...) fora do WHERE: com
-- ela, a materialized view não pode ser atualizada de forma incremental.

-- Fato de entrevistas: uma linha por entrevista, na versão vigente da silver (SCD tipo 2,
-- __END_AT vazio). A área vem do de-para de prefixos do nome da vaga, em minúsculas: vale o
-- prefixo mais longo que combinar ("auxiliar de cozinha" ganha de "auxiliar"); vaga sem
-- prefixo conhecido fica como Não classificada.
CREATE OR REFRESH MATERIALIZED VIEW ${catalogo}.${schema_gold}.gold_fato_entrevista (
  dt_entrevista DATE COMMENT 'Data da entrevista.',
  dt_mes_entrevista DATE COMMENT 'Primeiro dia do mês da entrevista, para agrupar por mês.',
  hr_entrevista STRING COMMENT 'Horário da entrevista no formato HH:mm.',
  nm_candidato STRING COMMENT 'Nome do candidato (dado pessoal: mascarado para quem não é do grupo de dados pessoais).' MASK ${catalogo}.${schema_silver}.mascarar_dado_pessoal,
  nm_vaga STRING COMMENT 'Nome da vaga como escrito na agenda.',
  nm_area STRING COMMENT 'Área da empresa, pelo prefixo do nome da vaga; Não classificada quando nenhum prefixo combina.',
  st_entrevista STRING COMMENT 'Resultado da entrevista padronizado (Aprovado, Reprovado, Não atendeu, Cancelado, Reagendado, Pendente).',
  st_situacao STRING COMMENT 'Situação para acompanhamento: Concluído, Em andamento, Pendente ou Não identificado.',
  nr_telefone STRING COMMENT 'Telefone do candidato (dado pessoal: já parcial na silver e mascarado aqui para quem não é do grupo de dados pessoais).' MASK ${catalogo}.${schema_silver}.mascarar_dado_pessoal,
  fl_compareceu BOOLEAN COMMENT 'Verdadeiro quando o candidato compareceu (Aprovado ou Reprovado).',
  fl_aprovado BOOLEAN COMMENT 'Verdadeiro quando o candidato foi aprovado.'
)
COMMENT 'Fato de entrevistas: uma linha por entrevista na versão vigente, com a área da vaga e as flags de comparecimento e aprovação.'
CLUSTER BY AUTO
TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'fato')
AS WITH de_para_area (ds_prefixo_vaga, nm_area) AS (
  VALUES
    ('cozinheir', 'Cozinha'),
    ('auxiliar de cozinha', 'Cozinha'),
    ('confeiteir', 'Cozinha'),
    ('esfiheiro', 'Cozinha'),
    ('atendente', 'Atendimento'),
    ('garçom', 'Atendimento'),
    ('bartender', 'Atendimento'),
    ('recreadora', 'Atendimento'),
    ('frentista', 'Atendimento'),
    ('recepcionista', 'Recepção'),
    ('secretária', 'Recepção'),
    ('auxiliar de limpeza', 'Limpeza e conservação'),
    ('limpeza', 'Limpeza e conservação'),
    ('doméstica', 'Limpeza e conservação'),
    ('domestica', 'Limpeza e conservação'),
    ('zeladora', 'Limpeza e conservação'),
    ('caseiro', 'Limpeza e conservação'),
    ('auxiliar administrativo', 'Administrativo'),
    ('auxiliar adminidtrativo', 'Administrativo'),
    ('auxixiar adminidtrativo', 'Administrativo'),
    ('assistente financeiro', 'Financeiro'),
    ('analista financeiro', 'Financeiro'),
    ('analista contábil', 'Financeiro'),
    ('operadora', 'Financeiro'),
    ('estoquista', 'Logística e produção'),
    ('auxiliar de estoque', 'Logística e produção'),
    ('auxiliar de produção', 'Logística e produção'),
    ('montador', 'Logística e produção'),
    ('tecnico operacional', 'Logística e produção'),
    ('eletricista', 'Logística e produção'),
    ('vendedor', 'Vendas'),
    ('auxiliar de loja', 'Vendas'),
    ('corretor', 'Vendas'),
    ('nail designer', 'Serviços especializados'),
    ('costureir', 'Serviços especializados'),
    ('advogad', 'Serviços especializados'),
    ('fisioterapeuta', 'Serviços especializados'),
    ('designer', 'Serviços especializados')
)
SELECT
  e.dt_entrevista,
  trunc(e.dt_entrevista, 'MM') AS dt_mes_entrevista,
  e.hr_entrevista,
  e.nm_candidato,
  e.nm_vaga,
  coalesce(a.nm_area, 'Não classificada') AS nm_area,
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
  e.st_entrevista = 'Aprovado' AS fl_aprovado
FROM silver_agenda AS e
LEFT JOIN de_para_area AS a
  ON lower(e.nm_vaga) LIKE a.ds_prefixo_vaga || '%'
WHERE e.__END_AT IS NULL
QUALIFY row_number() OVER (
  PARTITION BY e.dt_entrevista, e.nm_candidato
  ORDER BY length(a.ds_prefixo_vaga) DESC NULLS LAST, a.ds_prefixo_vaga
) = 1;
