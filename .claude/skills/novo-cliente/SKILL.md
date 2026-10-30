---
name: novo-cliente
description: Use quando eu pedir para adaptar o projeto a um novo cliente a partir dos arquivos CSV ou da lista de tabelas dele
---

# Adaptar o acelerador a um novo cliente

O objetivo é montar o `config/fontes.yml` do cliente e propor regras e indicadores
**antes de alterar qualquer arquivo**. Não execute comandos: só leia, crie e edite.

1. **Levantar as fontes.**
   - CSVs ou planilhas em `data/`: leia o cabeçalho e algumas dezenas de linhas de cada
     um. Anote separador, codificação, formatos de data, valores escritos de vários
     jeitos, linhas de total ou separadoras, campos vazios e dados pessoais.
   - Lista de tabelas (ERP, banco, Unity Catalog): anote colunas, tipos, chave e uma
     coluna crescente para carga incremental.
   - APIs: URL, autenticação, onde fica a lista de registros e a paginação.

2. **Propor, sem alterar nada:**
   - **Fontes**: uma tabela com nome, tipo, modo de carga (e por quê), chave primária,
     coluna de atualização e se precisa de `silver_<nome>.sql`;
   - **o `config/fontes.yml` completo** proposto;
   - **regras de qualidade** por fonte, cada uma com `drop` ou `alerta` e o motivo;
   - **dados pessoais** e como serão mascarados (LGPD);
   - **indicadores da gold**: 3 a 6 indicadores que respondem às perguntas do negócio,
     com as junções entre fontes, e as materialized views `gold_*` que os entregam;
   - **riscos**: dados insuficientes, chaves que não batem entre fontes, fontes que
     exigem acesso externo (banco e api só funcionam no Azure).

   **Pare aqui e espere meu OK.** Ajuste a proposta quantas vezes eu pedir.

3. **Aplicar, depois do OK:**
   - substitua `config/fontes.yml`;
   - crie os `src/pipeline/silver_<nome>.sql` necessários e remova os do cliente anterior;
   - substitua os `src/pipeline/gold_*.sql`;
   - atualize as `libraries` de `resources/pipeline.yml`;
   - atualize `setup/00_setup_free_edition.sql` com as tabelas de apoio, se houver;
   - ajuste os testes que citam fontes pelo nome (`agenda`, `cargos`) em
     `tests/test_projeto.py`;
   - atualize `README.md` e `docs/roteiro-de-operacao.md`.

4. **Lembrar dos dados reais**: confira que os arquivos do cliente estão cobertos pelo
   `.gitignore` antes de qualquer commit.

5. **Listar os comandos de validação** para eu rodar, sem rodar nenhum:

   ```
   ruff check .
   pytest -q
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   databricks bundle run essentials_carga_diaria -t dev
   ```
