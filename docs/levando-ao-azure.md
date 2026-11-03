# Levando o projeto ao Azure Databricks do cliente

O mesmo bundle roda no Azure Databricks do cliente pelo target `prod`. A nuvem é paga
diretamente à Microsoft, na assinatura do cliente, e os dados reais nunca saem dela
([ADR 0010](adr/0010-free-edition-so-com-dados-ficticios.md)). O deploy é feito só pelo
GitHub Actions ([ADR 0011](adr/0011-deploy-de-producao-por-oidc.md)).

## Passo a passo

1. **No Azure do cliente**: workspace Azure Databricks Premium com Unity Catalog, conta
   ADLS Gen2 com o contêiner `landing` e um Access Connector.
2. **No Unity Catalog**: storage credential, **external location** para
   `abfss://landing@<conta>.dfs.core.windows.net/` (o volume `landing` de prod é externo
   sobre ela), catálogo `prd` com `USE CATALOG` para os grupos do projeto, e os grupos
   da conta `essentials_engenharia`, `essentials_leitura_gold` e
   `essentials_dados_pessoais` (ou troque os nomes nas variáveis de `prod`). Os schemas,
   o volume e as permissões são criados pelo deploy
   ([ADR 0001](adr/0001-modelo-de-acesso-no-unity-catalog.md)).
3. **Fontes `tabela`**: troque `{catalogo}.{projeto}_origem...` no `config/fontes.yml`
   pelo nome real da tabela do cliente.
4. **Fontes `banco`**: crie a conexão (`CREATE CONNECTION`) e um catálogo estrangeiro
   **com o mesmo nome** (`CREATE FOREIGN CATALOG ... USING CONNECTION`), e troque
   `ingerir_banco` para `"true"` no `databricks.yml`
   ([ADR 0004](adr/0004-ingestao-so-com-fonte.md)).
5. **Fontes `api`**: crie o secret scope e guarde o token (`databricks secrets put-secret`),
   e troque `ingerir_api` para `"true"`.
6. **Service principal** de produção com acesso ao catálogo, à external location, às
   conexões e ao secret scope.
7. **No `databricks.yml`**: preencha o `host` de `prod`, `STORAGEACCOUNT`, o
   `service_principal_name`, o `cliente` (tag de custo) e o `usuario_alerta` (usuário do
   workspace que recebe o alerta de atraso). Para a view de custo, o service principal
   precisa de `SELECT` em `system.billing`; para separar o custo serverless por tag, o
   administrador cria uma política de uso serverless com as tags do projeto
   ([ADR 0003](adr/0003-monitoramento-fora-do-pipeline.md)).
8. **No GitHub**: environment `prod` com revisor obrigatório, variáveis
   `DATABRICKS_HOST_PROD` e `DATABRICKS_CLIENT_ID_PROD` e, no Databricks, a federation
   policy do service principal para o repositório (OIDC).
9. Rode o workflow **Deploy produção** e configure o **Azure Budgets** com o teto do
   diagnóstico.

## Depois do primeiro deploy

- Valide a máscara de dado pessoal com um usuário do grupo de leitura que não esteja no
  grupo de dados pessoais: ele deve ver `****` no nome e no telefone
  ([ADR 0002](adr/0002-dados-pessoais-no-unity-catalog.md)). No Free Edition isso não dá
  para conferir, porque só há um usuário.
- Entregue o [roteiro de operação](roteiro-de-operacao.md) com os nomes reais do projeto
  (skill `entrega`).
