# Retenção de dados e exclusão de titular

Decisão registrada no [ADR 0017](../adr/0017-retencao-e-exclusao-de-titular.md). Regras
gerais de dado pessoal em [`lgpd.md`](lgpd.md).

## Onde há dado pessoal

| Onde | O que guarda | Dado pessoal? |
| --- | --- | --- |
| Landing | o arquivo original, inteiro | sim |
| Bronze de snapshot | o arquivo inteiro, uma linha por arquivo (`value`) | sim |
| Silver e histórico SCD2 | colunas do contrato; as sensíveis mascaradas ou marcadas com a tag `pii` | sim, nas colunas `sensivel` |
| Gold | só com máscara de coluna para quem não é do grupo `grupo_dados_pessoais` | sim, mascarado |
| Views e tabelas `mon_*` | contagens, nomes de tabela, regra, nome do arquivo e motivo da falha | **não** |

As `mon_*` não têm dado pessoal de propósito: `mon_falhas` guarda só o nome da regra
(ADR 0015) e os avisos de arquivo mostram só o nome do arquivo. **Por isso o nome do
arquivo nunca pode ter dado pessoal.** Oriente quem envia arquivos a usar nomes como
`agenda_2025-12-15.csv`.

## Política de retenção

| Dado | Quanto tempo | Quem decide |
| --- | --- | --- |
| Landing e bronze de snapshot | só os últimos **N dias** (sugestão: 90) | o contrato com o cliente |
| Histórico SCD2 | pelo prazo do contrato | o contrato com o cliente |
| Time travel das tabelas Delta | `delta.deletedFileRetentionDuration` (7 dias) e `delta.logRetentionDuration` (30 dias), os padrões | decisão registrada para mudar |

Por que reter menos na landing e na bronze: cada arquivo de snapshot repete a planilha
inteira. Guardar todos multiplica o dado pessoal sem ganho, porque o retrato e o histórico
já ficam na silver.

**Ainda não é automatizado.** Hoje ninguém apaga os arquivos antigos da landing nem as
linhas antigas da bronze. A rotina de retenção de N dias é um próximo passo. Até lá, o
valor de N deve ser definido no contrato e a limpeza feita pelo procedimento de exclusão
abaixo, com aprovação.

## Exclusão de titular, passo a passo

Pedido do titular (LGPD, art. 18): apagar os dados de uma pessoa.

1. **Abra um chamado** e registre quem pediu, a data e a fonte. Não escreva o dado da
   pessoa no chamado.
2. **Aprovação:** o ponto focal do cliente (controlador) aprova a exclusão; a engenharia
   da Logos revisa o SQL antes de rodar.
3. **Gere o SQL** (nada é executado):

   ```
   python scripts/gerar_exclusao_titular.py --fonte agenda --catalogo <catalogo> \
       --schema <projeto> --schema-gold <projeto>_gold --saida exclusao.sql
   ```

   O titular entra só como parâmetro nomeado (`:titular_<coluna>`), preenchido no SQL
   editor do Databricks. Não grave o valor no arquivo nem no chamado, e não versione o
   `exclusao.sql`.
4. **Revise o SQL** e rode **passo a passo** no SQL editor, conferindo o `SELECT` de
   cada passo antes do `DELETE` ou `UPDATE`. Se a contagem for maior que a esperada,
   pare: o valor pode estar casando com outra pessoa.
5. **Os passos gerados**, em ordem:
   1. **Landing:** reescreva ou apague só os arquivos que citam o titular. Nunca apague a pasta.
   2. **Bronze:** um `UPDATE` tira do texto bruto só as linhas do titular.
   3. **Silver e histórico:** `DELETE` das linhas do titular.
   4. **Aviso de streaming:** veja a limitação abaixo.
   5. **Atualização normal do pipeline:** recalcula o retrato e a gold (materialized
      views). Nunca use full refresh.
   6. **`REORG TABLE ... APPLY (PURGE)`:** reescreve os arquivos sem as linhas apagadas.
   7. **`VACUUM DRY RUN`** e, **depois do prazo de retenção**, **`VACUUM`**. Até lá o dado
      ainda pode ser lido pelo time travel.
6. **Registre no chamado a data do passo 6** (`REORG`). A exclusão só termina depois do
   `VACUUM`: conte 7 dias para os arquivos (`deletedFileRetentionDuration`) e mantenha o
   chamado aberto até rodá-lo. Não reduza a retenção sem decisão registrada.
7. **Confira** na silver e na gold que o titular sumiu, com o mesmo parâmetro, e feche o
   chamado com a data do `VACUUM`.

## Limitação conhecida

As fontes `incremental` e `cdc` leem a bronze em streaming **sem** `skipChangeCommits`
(`src/pipeline/silver.py`). Um `UPDATE` ou `DELETE` na bronze quebraria a próxima carga
delas. O script avisa isso no passo 4. A agenda (snapshot) não tem esse problema. Antes de
excluir titular numa fonte incremental ou cdc, a opção precisa entrar no código.

## Mudar o schema da bronze

O `pipelines.reset.allowed = false` impede o full refresh, que seria o caminho comum para
refazer a bronze com outro schema. Por isso, esse caso é manual:

1. Registre a decisão (ADR ou chamado) e a aprovação do João.
2. Remova a propriedade da tabela, por PR, e implante.
3. Faça a mudança de schema e a carga.
4. Restaure a propriedade por outro PR.

Tabelas de fonte `tabela` não têm essa trava (a bronze é uma cópia recalculável).
