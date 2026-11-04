-- View da gold lida pelo painel de entrevistas: a fato mais os campos que dependem da data
-- de hoje (que não podem ficar na materialized view sem impedir a atualização incremental).
-- Criada pela tarefa governanca_depois, depois do pipeline: a view de pipeline (CREATE VIEW)
-- não aplica o COMMENT de cada coluna, e o dicionário de dados exige descrição em todas.
-- ${catalogo} e ${schema_gold} são trocados pelo catálogo e pelo schema gold do target.
-- As colunas com dado pessoal chegam já mascaradas pela fato (MASK).
CREATE OR REPLACE VIEW ${catalogo}.${schema_gold}.gold_vw_entrevistas (
  dt_entrevista COMMENT 'Data da entrevista.',
  dt_mes_entrevista COMMENT 'Primeiro dia do mês da entrevista, para agrupar por mês.',
  hr_entrevista COMMENT 'Horário da entrevista no formato HH:mm.',
  nm_candidato COMMENT 'Nome do candidato (dado pessoal: mascarado para quem não é do grupo de dados pessoais).',
  nm_vaga COMMENT 'Nome da vaga como escrito na agenda.',
  nm_area COMMENT 'Área da empresa, pelo prefixo do nome da vaga; Não classificada quando nenhum prefixo combina.',
  st_entrevista COMMENT 'Resultado da entrevista padronizado (Aprovado, Reprovado, Não atendeu, Cancelado, Reagendado, Pendente).',
  st_situacao COMMENT 'Situação para acompanhamento: Concluído, Em andamento, Pendente ou Não identificado.',
  nr_telefone COMMENT 'Telefone do candidato (dado pessoal: já parcial na silver e mascarado para quem não é do grupo de dados pessoais).',
  fl_compareceu COMMENT 'Verdadeiro quando o candidato compareceu (Aprovado ou Reprovado).',
  fl_aprovado COMMENT 'Verdadeiro quando o candidato foi aprovado.',
  fl_sem_retorno COMMENT 'Verdadeiro quando a entrevista já passou (antes de hoje) e o resultado não foi registrado.'
)
COMMENT 'Entrevistas para o painel: a fato gold_fato_entrevista mais o que depende da data de hoje (entrevista sem retorno).'
TBLPROPERTIES ('camada' = 'gold', 'tipo' = 'view')
AS SELECT
  f.dt_entrevista,
  f.dt_mes_entrevista,
  f.hr_entrevista,
  f.nm_candidato,
  f.nm_vaga,
  f.nm_area,
  f.st_entrevista,
  f.st_situacao,
  f.nr_telefone,
  f.fl_compareceu,
  f.fl_aprovado,
  -- A entrevista já passou e ninguém registrou o resultado.
  f.st_entrevista = 'Pendente' AND f.dt_entrevista < current_date() AS fl_sem_retorno
FROM ${catalogo}.${schema_gold}.gold_fato_entrevista AS f;
