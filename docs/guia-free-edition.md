# Guia: rodar o projeto no Databricks Free Edition

O Free Edition roda **somente os dados fictícios** do gerador
(`data/gerar_dados_exemplo.py`). Os arquivos têm o mesmo formato da planilha real do
RH (cabeçalho, linhas `AGENDA DIA`, `;`, UTF-8 com BOM, CRLF e a mesma sujeira), mas
nomes e telefones inventados. Dados reais de clientes nunca entram aqui
([ADR 0010](adr/0010-free-edition-so-com-dados-ficticios.md)).

## Passo a passo

1. **Crie a conta** no [Databricks Free Edition](https://www.databricks.com/learn/free-edition)
   e anote a URL do workspace.
2. **Instale a CLI do Databricks**:
   - Windows: `winget install Databricks.DatabricksCLI`
   - macOS: `brew tap databricks/tap && brew install databricks`
3. **Faça login**: `databricks auth login --host https://<seu-workspace>.cloud.databricks.com`
4. **Configuração local, fora do repositório**: o host do workspace vem do perfil criado
   no login (passo 3), e o e-mail de alerta, da variável `BUNDLE_VAR_alert_email` (no
   PowerShell, `$env:BUNDLE_VAR_alert_email = "voce@exemplo.com"`) ou de
   `--var="alert_email=voce@exemplo.com"` no `deploy`. Nenhum dos dois é versionado.
5. **Rode o setup**: no **SQL Editor**, execute `setup/00_setup_free_edition.sql`. Ele
   cria só o que não pertence ao bundle: o catálogo `essentials` e o `USE CATALOG` do grupo
   de leitura.
6. **Valide e implante**: o deploy cria os quatro schemas do projeto (bronze, silver, gold e
   monitoramento), o volume `landing`, as permissões, o job, o pipeline, os painéis e o
   alerta. Nos comandos abaixo, `<schema>` é o prefixo de dev, `dev_<seu usuário>_portfolio`
   (o `deploy` mostra os nomes), e cada schema leva o sufixo da camada:
   `<schema>_bronze`, `<schema>_silver`, `<schema>_gold` e `<schema>_monitoramento`.
   ```
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   ```
7. **Gere as agendas fictícias e envie a versão 1** para a pasta da fonte no volume. A
   pasta precisa existir antes do envio, e o pipeline falha se ela estiver vazia:
   ```
   python data/gerar_dados_exemplo.py
   databricks fs mkdir dbfs:/Volumes/essentials/<schema>_bronze/landing/agenda
   databricks fs cp data/agenda_exemplo_v1.csv dbfs:/Volumes/essentials/<schema>_bronze/landing/agenda/
   databricks bundle run essentials_carga_diaria -t dev
   ```
8. **Confira**: no SQL Editor, consulte `essentials.<schema>_gold.gold_vw_entrevistas`.
   No pipeline, a aba **Data quality** do nó `silver_int_agenda_retrato` mostra as linhas
   descartadas (as 2 entrevistas sem nome do gerador) e os alertas (telefones inválidos,
   status "Talvez", entrevista sem horário). O retrato é privado do pipeline: ele aparece no
   desenho do pipeline, mas não no Catalog. O histórico dia a dia fica em
   `essentials.<schema>_monitoramento.mon_qualidade_diaria` e no painel "Saúde da
   plataforma".
9. **Segunda carga (snapshot e histórico)**: a versão 2 é a mesma planilha reenviada
   inteira, com o status preenchido nas entrevistas que estavam vazias e mais um dia de
   agenda:
   ```
   databricks fs cp data/agenda_exemplo_v2.csv dbfs:/Volumes/essentials/<schema>_bronze/landing/agenda/
   databricks bundle run essentials_carga_diaria -t dev
   ```
   A bronze lê só o arquivo novo e a `silver_agenda` (SCD tipo 2) guarda as duas versões de
   cada entrevista que mudou: a antiga, fechada (`__END_AT` preenchido), e a nova, vigente
   (`__END_AT` vazio). Para conferir no SQL Editor:
   ```sql
   -- Entrevistas que mudaram: a versão antiga fechada (__END_AT preenchido) e a nova aberta.
   SELECT dt_entrevista, nm_candidato, st_entrevista, __START_AT, __END_AT
   FROM essentials.<schema>_silver.silver_agenda
   WHERE (dt_entrevista, nm_candidato) IN (
     SELECT dt_entrevista, nm_candidato
     FROM essentials.<schema>_silver.silver_agenda
     GROUP BY ALL HAVING count(*) > 1
   )
   ORDER BY nm_candidato, __START_AT;
   ```

## Totais esperados

Como o gerador usa semente fixa, os números são sempre os mesmos (são os que os testes de
integração conferem, em `tests/integracao/esperado.py`):

| Depois da | Retrato | Versões vigentes (`__END_AT` vazio) | Versões na silver | Versões fechadas | Descartes (`nome_preenchido`) |
|---|---|---|---|---|---|
| v1 | 229 | 227 | 227 | 0 | 2 |
| v2 | 236 | 234 | 252 | 18 | 2 |

A `gold_fato_entrevista` tem uma linha por versão vigente (227 e 234), e a
`gold_vw_entrevistas` tem o mesmo total.

## Bom saber

- Quem já tinha o ambiente de dev com os dois schemas antigos (`dev_<usuário>_portfolio` e
  `_gold`) não migra sozinho: veja o passo `unbind` em
  [levando ao Azure](levando-ao-azure.md) (seção "Migrar um ambiente que já existe").
- No modo development, o job e o pipeline ganham o prefixo `[dev <usuário>]`, e o
  agendamento das 6h e o alerta de atraso ficam pausados (`databricks.yml`): a carga roda
  quando você manda.
- O Free Edition tem cota diária de uso. Depois de muitas cargas no mesmo dia, ele pode
  recusar novas execuções de job por algumas horas ("Triggering new runs ... is currently
  disabled temporarily").
- O Free Edition é só para aprendizado e uso pessoal e não pode ser usado
  comercialmente: projetos de clientes rodam no Azure Databricks do cliente
  ([levando ao Azure](levando-ao-azure.md)).
