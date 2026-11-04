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
7. **No `databricks.yml`** (target `prod`): o `host`, o `service_principal_name`, a
   `landing_url` (endereço da external location da landing), o `cliente` (tag de custo),
   o `usuario_alerta` (usuário do workspace que recebe os alertas), o
   `teto_custo_mensal_usd` (teto do Databricks no diagnóstico), o `email_suporte` e o
   `destino_suporte_id` (destino de notificação de e-mail do suporte da Logos, criado pelo
   administrador em **Settings > Notifications**). Para as views de custo e de execuções,
   o service principal precisa de `SELECT` em `system.billing` e em `system.lakeflow`;
   para separar o custo serverless por tag, o administrador cria uma política de uso
   serverless com as tags do projeto
   ([ADR 0003](adr/0003-monitoramento-fora-do-pipeline.md),
   [ADR 0015](adr/0015-aviso-de-falha-com-motivo.md)).
8. **No GitHub**: environment `prod` com revisor obrigatório, variáveis
   `DATABRICKS_HOST_PROD` e `DATABRICKS_CLIENT_ID_PROD` e, no Databricks, a federation
   policy do service principal para o repositório (OIDC).
9. Rode o workflow **Deploy produção** e configure o **Azure Budgets** com o teto do
   diagnóstico.

## Como o cliente envia os arquivos

A landing é o contêiner `landing` da conta ADLS Gen2, uma pasta por fonte
(`<projeto>/<fonte>`). O padrão é dar à equipe do cliente um acesso **só de gravação na
pasta da fonte**: uma SAS de contêiner com permissão de gravação e criação, com
validade definida, ou um papel de colaborador de dados no escopo da pasta (ACL do ADLS),
usado pelo **Azure Storage Explorer**. Ninguém do cliente precisa de acesso ao
Databricks para enviar arquivos.

- **SFTP** do próprio storage é uma opção para sistemas que só exportam por SFTP; é
  cobrado por hora enquanto está habilitado, então entra só se o diagnóstico pedir.
- Planilhas Excel (`.xlsx`) são lidas diretamente (formato `excel` no `fontes.yml`).
- **Outra nuvem** (AWS ou GCP, sob orçamento à parte): o pipeline não muda; troque a
  `landing_url` (`s3://` ou `gs://`), a external location e o canal de envio
  equivalente da nuvem.

## Depois do primeiro deploy

- Valide a máscara de dado pessoal com um usuário do grupo de leitura que não esteja no
  grupo de dados pessoais: ele deve ver `****` no nome e no telefone
  ([ADR 0002](adr/0002-dados-pessoais-no-unity-catalog.md)). No Free Edition isso não dá
  para conferir, porque só há um usuário.
- Confira que os quatro alertas SQL (falha, volume e estrutura, atraso e custo) estão
  ativos e inscritos para o usuário do cliente e para o destino do suporte.
- Entregue o [roteiro de operação](roteiro-de-operacao.md) com os nomes reais do projeto
  (skill `entrega`).
