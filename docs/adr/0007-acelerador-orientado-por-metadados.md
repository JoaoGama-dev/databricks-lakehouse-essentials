# 0007. Acelerador orientado por metadados (config/fontes.yml)

- **Status:** aceita
- **Data:** 2026-10-30 (registrada em 2026-11-03)

## Contexto

Cada cliente do pacote Essentials tem fontes diferentes (planilhas, tabelas, bancos,
APIs), mas a bronze e a silver fazem quase sempre o mesmo: ler, padronizar nomes, limpar
texto e datas, aplicar regras de qualidade, mascarar dado pessoal e guardar o histórico.
Reescrever isso por cliente multiplica código, testes e erros.

## Decisão

As fontes de cada projeto são descritas em **`config/fontes.yml`**, validado por
**`config/fontes.schema.json`**. A bronze e a silver são **genéricas**
(`src/pipeline/bronze.py` e `silver.py`) e geram as tabelas de cada fonte a partir dele.
A lógica que vem da config (nomes, expectations, expressões de limpeza, schema da
silver) fica em `src/essentials/config_fontes.py`, sem Spark, testada pelo pytest. O que
é específico de uma fonte vai para `src/pipeline/silver_<fonte>.sql`; a gold é escrita à
mão em SQL.

## Alternativas consideradas

- **Pipeline escrito à mão por cliente:** máxima liberdade, mas sem reaproveitamento e
  com padrões (nomes, dicionário, LGPD) dependendo da disciplina de cada pessoa.
- **Gerar código a partir da config (templates de SQL/Python):** o código gerado
  divergiria do gerador com o tempo e teria de ser revisado a cada geração.
- **Config em tabela no Unity Catalog:** mudanças sairiam do Git, sem PR nem CI.

## Consequências

- Adaptar a um cliente é, na maior parte, trocar o `fontes.yml` (skills `novo-cliente`
  e `nova-fonte`).
- Padrões viram validação: prefixo de coluna × tipo, `descricao` obrigatória, regra
  `nao_nulo` com `drop` na chave, `mascarar` exigindo `sensivel: true`.
- Um campo novo na config exige atualizar o schema JSON, os comentários do YAML e
  `config_fontes.py`, com testes.
- Casos fora do padrão precisam de `preparacao_sql`; se ficarem frequentes, o acelerador
  ganha um recurso novo, não um desvio por cliente.
