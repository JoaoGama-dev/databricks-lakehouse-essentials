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
   `essentials_dados_pessoais` (ou troque os nomes nas variáveis de `prod`). Os quatro
   schemas (`<projeto>_bronze`, `<projeto>_silver`, `<projeto>_gold` e
   `<projeto>_monitoramento`), o volume e as permissões são criados pelo deploy
   ([ADR 0018](adr/0018-schemas-por-camada.md)).
3. **Fontes `tabela`**: o exemplo não tem fonte desse tipo. Se o cliente tiver, informe em
   `nome_completo` o nome real da tabela dele (`catalogo.schema.tabela`).
4. **Fontes `banco`**: crie a conexão (`CREATE CONNECTION`) e um catálogo estrangeiro
   **com o mesmo nome** (`CREATE FOREIGN CATALOG ... USING CONNECTION`), e troque
   `ingerir_fontes_externas` para `"true"` no `databricks.yml`
   ([ADR 0004](adr/0004-ingestao-so-com-fonte.md)).
5. **Fontes `api`**: crie o secret scope e guarde o token (`databricks secrets put-secret`),
   e troque `ingerir_fontes_externas` para `"true"` (a mesma variável serve a banco e API).
6. **Service principal** de produção com acesso ao catálogo, à external location, às
   conexões e ao secret scope.
7. **No `databricks.yml`** (target `prod`): o `host`, o `service_principal_name`, a
   `landing_url` (endereço da external location da landing), o `cliente` (tag de custo),
   o `usuario_alerta` (usuário do workspace que recebe os alertas), o
   `teto_custo_mensal_usd` (teto do Databricks no diagnóstico), o `email_suporte` e o
   `destino_suporte_id` (destino de notificação de e-mail do suporte da Logos, criado pelo
   administrador em **Settings > Notifications**). Os pontos de custo e de aviso estão na
   seção "Custo real, warehouse dedicado e avisos" abaixo
   ([ADR 0021](adr/0021-tarefa-final-de-monitoramento-e-aviso-de-falha-na-hora.md),
   [ADR 0023](adr/0023-custo-do-projeto-por-tag-e-projecao.md)).
8. **No GitHub**: environment `prod` com revisor obrigatório, variáveis
   `DATABRICKS_HOST_PROD` e `DATABRICKS_CLIENT_ID_PROD` e, no Databricks, a federation
   policy do service principal para o repositório (OIDC).
9. Rode o workflow **Deploy produção** e configure o **Azure Budgets** com o teto do
   diagnóstico.

## Custo real, warehouse dedicado e avisos

**O que o custo mostra.** As views `mon_custo_*` atribuem o consumo pela tag `projeto`
(jobs pela cobrança e por `system.lakeflow.jobs`; pipelines por `system.lakeflow.pipelines`),
em `dev`, `ci` e `prod`, a preço de lista. Referência medida no dev em 2026-11-05: cerca de
US$ 0,12 por carga no `dev` e US$ 0,17 no `ci`; para uma carga diária de volume parecido,
de US$ 3 a 6 por mês de job e pipeline, **mais** warehouse e armazenamento. Uma carga que
falha custou cerca de US$ 0,70 no `ci`, por causa das novas tentativas do pipeline. Esses
números são do Free Edition: confirme no ambiente do cliente.

**Warehouse dedicado.**

- O faturamento do SQL warehouse não traz a tag `projeto`. Por isso o custo dele só entra
  nas views quando a variável `warehouse_dedicado` é `"true"` (padrão `"false"`).
- **Use `"true"` só com um warehouse exclusivo do projeto**; num warehouse compartilhado,
  o custo de outros usos entraria na conta do projeto.
- No cliente, o recomendado é criar um warehouse exclusivo e usá-lo em `warehouse_id`,
  inclusive nas tarefas `avisar_falha` e `encerrar_com_falha`, que também usam warehouse.
- Armazenamento e otimização preditiva ficam fora do custo do projeto.

**Tag `projeto`.** A atribuição só funciona se os recursos levam a tag. O bundle a coloca no
job e no pipeline; no cliente, imponha-a por **política**, a cargo do
administrador (como a política de uso serverless), para ninguém criar recurso sem ela.

**Grants.**

- O service principal de prod precisa de `SELECT` em `system.billing` e `system.lakeflow`,
  concedido pelo **metastore admin**. Sem isso, as views de custo e de execuções não são
  criadas, e o log mostra só um aviso (a carga não falha).
- Para as tarefas `avisar_falha` (`alert_task`) e `encerrar_com_falha` (`sql_task`), o
  service principal precisa de `CAN_USE` no warehouse e `CAN_RUN` no alerta `falha_carga`.

**Aviso de falha na hora.** A tarefa `avisar_falha` avalia o alerta `falha_carga` assim que
a carga falha; o agendamento das 7h fica como rede de segurança. Em prod, confirme que o
suporte da Logos está inscrito no alerta. No `ci`, a `avisar_falha` pode mandar e-mail se a
integração falhar.

**Token de dev do CI.** O token que o CI usa no Free Edition expira por volta de
2027-01-28: rotacione antes (secret `DATABRICKS_TOKEN_DEV`).

## Otimização preditiva: decisão do administrador

A otimização preditiva (limpeza e compactação automáticas das tabelas gerenciadas) é
configurada pelo **administrador da conta ou do metastore** do cliente, não pelo bundle.
O projeto não a liga nem a desliga. Vale combinar com o cliente antes do primeiro deploy:
com ela ligada, o `VACUUM` e a compactação das materialized views e da silver ficam por
conta do Databricks; sem ela, a manutenção e o prazo de retenção
(`docs/padroes/retencao-e-exclusao.md`) precisam ser agendados por quem opera. A exclusão
de titular depende dessa limpeza para os arquivos antigos das materialized views sumirem.

## Migrar um ambiente que já existe

Um ambiente criado antes da separação por camadas (dois schemas, `<projeto>` e
`<projeto>_gold`) **não migra sozinho** com um `bundle deploy`: o bundle passaria a criar os
quatro schemas novos e trataria os antigos como recursos a apagar, com os dados dentro. A
solução é **soltar do estado do bundle** o schema antigo e o volume antigo, sem apagar nada
no workspace, e só então implantar. Foi o que se fez no ambiente de dev, com a CLI 1.22.1
(confira com `databricks bundle deployment unbind --help` na versão em uso). Em produção, o
procedimento roda pelo workflow de deploy e com aprovação, nunca por comando local (ADR 0011):

1. **Rode o `unbind` a partir do código antigo** (o da `main` antes da mudança, onde as
   chaves ainda existem), para o schema antigo e para o volume:
   `databricks bundle deployment unbind projeto -t <target>` e
   `databricks bundle deployment unbind landing -t <target>`. O `unbind` só tira o vínculo;
   os objetos continuam no Unity Catalog.
2. **Veja o plano** com o código novo: `databricks bundle plan -t <target>`. Ele precisa
   terminar em `0 to delete`. Se aparecer qualquer exclusão, pare.
3. **Implante.** O bundle cria os quatro schemas novos e o volume novo.
4. **Leve os arquivos da landing** para o volume novo e rode a carga. A silver e a gold são
   recalculadas da bronze. O histórico SCD2 acumulado nas cargas antigas **não** se refaz a
   partir de arquivos reenviados de uma vez: se ele importa, copie a tabela antiga antes de
   apagar o schema antigo.
5. **Só depois de conferir**, apague os objetos antigos **pelo nome exato**, com a lista
   conferida antes. Nunca por filtro.

Em um cliente, registre o plano num chamado e peça aprovação antes do passo 5.

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
  grupo de dados pessoais: ele deve ver `****` no nome e no telefone, **na fato e na view
  `gold_vw_entrevistas`** ([ADR 0002](adr/0002-dados-pessoais-no-unity-catalog.md) e
  [ADR 0020](adr/0020-exemplo-sem-cargos-e-view-que-mascara.md)). No Free Edition isso não
  dá para conferir, porque só há um usuário.
- Confira que os quatro alertas SQL (falha, volume e estrutura, atraso e custo) estão
  ativos e inscritos para o usuário do cliente e para o destino do suporte.
- Force uma falha de teste num ambiente de homologação, se houver, e confira o e-mail com o
  motivo logo depois da falha. Nunca force falha em prod.
- Confira no painel "Saúde" (página "Saúde da plataforma") que o custo do mês aparece por
  ambiente; se estiver vazio, revise os grants de `system.billing` e `system.lakeflow`.
- Entregue o [roteiro de operação](roteiro-de-operacao.md) com os nomes reais do projeto
  (skill `entrega`).
