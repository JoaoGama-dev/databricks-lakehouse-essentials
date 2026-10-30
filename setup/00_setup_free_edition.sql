-- Preparação do Free Edition: rode uma vez no SQL Editor antes do primeiro deploy.

-- Schema das tabelas do lakehouse e Volume que serve de landing zone.
-- Cada fonte do tipo arquivo tem sua pasta: /Volumes/workspace/essentials/landing/<caminho>/
CREATE SCHEMA IF NOT EXISTS workspace.essentials
COMMENT 'Lakehouse do pacote Essentials: bronze, silver e gold.';

CREATE VOLUME IF NOT EXISTS workspace.essentials.landing
COMMENT 'Landing zone: arquivos recebidos das fontes, uma pasta por fonte.';

-- Tabela de apoio que simula um sistema de origem do cliente (fonte "cargos", tipo tabela).
-- Liga o começo do nome da vaga, em minúsculas, a uma área da empresa.
CREATE SCHEMA IF NOT EXISTS workspace.origem
COMMENT 'Simula os sistemas de origem do cliente no Free Edition.';

CREATE OR REPLACE TABLE workspace.origem.cadastro_cargos (
  id_cargo INT COMMENT 'Identificador do cargo',
  prefixo_vaga STRING COMMENT 'Começo do nome da vaga, em minúsculas; o mais longo que combinar vence',
  area STRING COMMENT 'Área da empresa',
  atualizado_em TIMESTAMP COMMENT 'Última alteração do cadastro'
)
COMMENT 'Cadastro de cargos do RH: prefixo do nome da vaga e área.';

INSERT INTO workspace.origem.cadastro_cargos VALUES
  (1, 'cozinheir', 'Cozinha', current_timestamp()),
  (2, 'auxiliar de cozinha', 'Cozinha', current_timestamp()),
  (3, 'confeiteir', 'Cozinha', current_timestamp()),
  (4, 'esfiheiro', 'Cozinha', current_timestamp()),
  (5, 'atendente', 'Atendimento', current_timestamp()),
  (6, 'garçom', 'Atendimento', current_timestamp()),
  (7, 'bartender', 'Atendimento', current_timestamp()),
  (8, 'recreadora', 'Atendimento', current_timestamp()),
  (9, 'frentista', 'Atendimento', current_timestamp()),
  (10, 'recepcionista', 'Recepção', current_timestamp()),
  (11, 'secretária', 'Recepção', current_timestamp()),
  (12, 'auxiliar de limpeza', 'Limpeza e conservação', current_timestamp()),
  (13, 'limpeza', 'Limpeza e conservação', current_timestamp()),
  (14, 'doméstica', 'Limpeza e conservação', current_timestamp()),
  (15, 'domestica', 'Limpeza e conservação', current_timestamp()),
  (16, 'zeladora', 'Limpeza e conservação', current_timestamp()),
  (17, 'caseiro', 'Limpeza e conservação', current_timestamp()),
  (18, 'auxiliar administrativo', 'Administrativo', current_timestamp()),
  (19, 'auxiliar adminidtrativo', 'Administrativo', current_timestamp()),
  (20, 'auxixiar adminidtrativo', 'Administrativo', current_timestamp()),
  (21, 'assistente financeiro', 'Financeiro', current_timestamp()),
  (22, 'analista financeiro', 'Financeiro', current_timestamp()),
  (23, 'analista contábil', 'Financeiro', current_timestamp()),
  (24, 'operadora', 'Financeiro', current_timestamp()),
  (25, 'estoquista', 'Logística e produção', current_timestamp()),
  (26, 'auxiliar de estoque', 'Logística e produção', current_timestamp()),
  (27, 'auxiliar de produção', 'Logística e produção', current_timestamp()),
  (28, 'montador', 'Logística e produção', current_timestamp()),
  (29, 'tecnico operacional', 'Logística e produção', current_timestamp()),
  (30, 'eletricista', 'Logística e produção', current_timestamp()),
  (31, 'vendedor', 'Vendas', current_timestamp()),
  (32, 'auxiliar de loja', 'Vendas', current_timestamp()),
  (33, 'corretor', 'Vendas', current_timestamp()),
  (34, 'nail designer', 'Serviços especializados', current_timestamp()),
  (35, 'costureir', 'Serviços especializados', current_timestamp()),
  (36, 'advogad', 'Serviços especializados', current_timestamp()),
  (37, 'fisioterapeuta', 'Serviços especializados', current_timestamp()),
  (38, 'designer', 'Serviços especializados', current_timestamp());
