---
name: nova-fonte
description: Use quando eu pedir para incluir uma nova fonte de dados ou um novo arquivo no pipeline
---

# Incluir uma nova fonte de dados

A bronze e a silver são geradas a partir do `config/fontes.yml`. Incluir uma fonte é,
quase sempre, só acrescentar um item nele. Siga os passos na ordem e não execute
comandos: só leia, crie e edite arquivos.

1. **Analisar a fonte.**
   - Arquivo: leia o cabeçalho e algumas linhas; anote separador, codificação,
     formatos de data, valores escritos de vários jeitos, campos vazios e dados pessoais.
   - Tabela, banco ou API: peça ou leia a lista de colunas e tipos.
   - Defina `tipo`, `modo_carga` (incremental, snapshot ou cdc), `chave_primaria` e
     `coluna_atualizacao`.
   - Veja se a estrutura cabe na limpeza padrão. Se não couber (ex.: data só numa linha
     separadora, cabeçalho em várias linhas), vai precisar de `silver_<nome>.sql`.

2. **Propor e esperar a aprovação.** Mostre:
   - o bloco YAML completo da fonte, com `colunas` (tipo, formatos, caixa, de-para,
     máscara) e `regras` (nao_nulo, valores_aceitos, expressao, unico), cada regra com
     `drop` ou `alerta` e o motivo;
   - se vai criar `silver_<nome>.sql` e o que ele fará;
   - se há gold nova ou alterada.

   **Pare aqui e espere meu OK.**

3. **Aplicar:**
   - acrescente a fonte em `config/fontes.yml`, seguindo os comentários do arquivo;
   - se precisar, crie `src/pipeline/silver_<nome>.sql` com
     `CREATE TEMPORARY VIEW preparada_<nome>` lendo `bronze_<nome>`, marque
     `preparacao_sql: true` e inclua o arquivo nas `libraries` de `resources/pipeline.yml`;
   - gold nova ou alterada em `src/pipeline/gold_*.sql`, com COMMENT e
     `TBLPROPERTIES ('camada' = 'gold')`;
   - para tipo tabela no Free Edition, inclua a criação da tabela em
     `setup/00_setup_free_edition.sql`.

4. **Atualizar o resto:** testes específicos em `tests/test_projeto.py` (quando houver
   lógica nova), `README.md` (tabela de fontes) e `docs/roteiro-de-operacao.md` (onde
   colocar o arquivo e as novas regras da aba Data quality, em linguagem não técnica).

5. **Listar os comandos de validação** para eu rodar, sem rodar nenhum:

   ```
   ruff check .
   pytest -q
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   databricks bundle run essentials_carga_diaria -t dev
   ```
