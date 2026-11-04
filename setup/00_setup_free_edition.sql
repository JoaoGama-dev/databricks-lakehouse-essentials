-- Preparação do Free Edition: rode uma vez antes do primeiro deploy do projeto.
--
-- Este arquivo cria só o que NÃO pertence ao bundle do projeto:
--   catálogo essentials             um só para todos os projetos do pacote
-- Os schemas do projeto (<projeto>_bronze, <projeto>_silver, <projeto>_gold e
-- <projeto>_monitoramento), o volume landing e as permissões são criados pelo bundle
-- (resources/governanca.yml) no "databricks bundle deploy".

CREATE CATALOG IF NOT EXISTS essentials
COMMENT 'Pacote Essentials da Logos Analytics: um schema por projeto e camada.';

-- O grupo de leitura (variável grupo_leitura_gold; no Free Edition, "account users")
-- precisa entrar no catálogo para chegar ao schema gold, onde o bundle dá o SELECT.
GRANT USE CATALOG ON CATALOG essentials TO `account users`;
