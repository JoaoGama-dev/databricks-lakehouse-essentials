---
name: novo-cliente
description: Use quando eu pedir para adaptar o projeto a um novo cliente a partir dos arquivos CSV ou da lista de tabelas dele
---

# Começar um novo projeto do pacote Essentials

O objetivo é montar o projeto do cliente seguindo a estrutura do pacote (catálogo
`essentials`, um schema por projeto, bundle `essentials_<projeto>`) e propor fontes,
regras e indicadores **antes de alterar qualquer arquivo**. Não execute comandos: só
leia, crie e edite.

1. **Definir o nome do projeto** em snake_case (ex.: `clinica_vida`). Ele vira o schema
   `essentials.<projeto>`, o bundle `essentials_<projeto>` e o repositório
   `essentials-<projeto>`.

2. **Levantar as fontes.**
   - CSVs ou planilhas em `data/`: leia o cabeçalho e algumas dezenas de linhas de cada
     um. Anote separador, codificação, formatos de data, valores escritos de vários
     jeitos, linhas de total ou separadoras, campos vazios e dados pessoais.
   - Lista de tabelas (ERP, banco, Unity Catalog): anote colunas, tipos, chave e uma
     coluna crescente para carga incremental.
   - APIs: URL, autenticação, onde fica a lista de registros e a paginação.

3. **Propor, sem alterar nada:**
   - **Fontes**: uma tabela com nome, tipo, modo de carga (e por quê), chave primária,
     coluna de atualização e se precisa de `silver_<fonte>.sql`;
   - **de-para de colunas** por fonte: nome na origem → nome padronizado com prefixo da
     classe da informação (`id_ cd_ nm_ ds_ sg_ st_ nr_ qt_ vl_ pc_ dt_ dh_ hr_ fl_`) → tipo;
   - **o `config/fontes.yml` completo** proposto;
   - **regras de qualidade** por fonte, cada uma com `drop` ou `alerta` e o motivo (em
     snapshot e cdc, `nao_nulo` com `drop` em cada coluna da chave);
   - **dados pessoais** e como serão mascarados (LGPD);
   - **modelo da gold** em estrela: `gold_dim_*`, `gold_fato_*` e `gold_agg_*`, com 3 a 6
     indicadores que respondem às perguntas do negócio e as junções entre fontes;
   - **riscos**: dados insuficientes, chaves que não batem entre fontes, fontes que
     exigem acesso externo (banco e api só funcionam no Azure).

   **Pare aqui e espere meu OK.** Ajuste a proposta quantas vezes eu pedir.

4. **Aplicar, depois do OK:**
   - no `databricks.yml`, `bundle.name: essentials_<projeto>` e o `default` da variável
     `projeto`;
   - em `setup/00_setup_free_edition.sql`, troque o nome do projeto anterior pelo novo e
     inclua as tabelas de apoio em `essentials.<projeto>_origem`;
   - substitua `config/fontes.yml`;
   - crie os `src/pipeline/silver_<fonte>.sql` necessários e remova os do projeto anterior;
   - substitua os `src/pipeline/gold_*.sql`;
   - atualize as `libraries` de `resources/pipeline.yml`;
   - ajuste os testes que citam fontes ou colunas pelo nome (`agenda`, `cargos`,
     `dt_entrevista`...) em `tests/test_projeto.py`;
   - atualize `README.md`, `CLAUDE.md` e `docs/roteiro-de-operacao.md`.

5. **Lembrar dos dados reais**: confira que os arquivos do cliente estão cobertos pelo
   `.gitignore` antes de qualquer commit, e que dados reais só vão para o ambiente do
   cliente, nunca para o Free Edition.

6. **Listar os comandos de validação** para eu rodar, sem rodar nenhum:

   ```
   ruff check .
   pytest -q
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   databricks bundle run essentials_carga_diaria -t dev
   ```
