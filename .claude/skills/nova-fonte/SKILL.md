---
name: nova-fonte
description: Use quando eu pedir para incluir uma nova fonte de dados ou um novo arquivo no pipeline
---

# Incluir uma nova fonte de dados

A bronze e a silver são geradas a partir do `config/fontes.yml`. Incluir uma fonte é,
quase sempre, só acrescentar um item nele. Siga os passos na ordem. Regras de LGPD em
`docs/padroes/lgpd.md`.

1. **Analisar a fonte pelo perfil, nunca pelo conteúdo.**
   - Arquivo: ele fica em `data/privado/` (ignorado pelo Git e bloqueado pelos hooks).
     Rode `python scripts/perfilar_dados.py data/privado/<arquivo>` e trabalhe
     **exclusivamente** com a saída: separador, codificação, BOM, linhas estruturais,
     tipos, padrões de formato, nulos e colunas marcadas como sensíveis. Não tente ler o
     arquivo de outro jeito; se o perfil não bastar, pergunte ao usuário.
   - Tabela, banco ou API: peça a lista de colunas e tipos (sem amostra de linhas).
   - Defina `tipo`, `modo_carga` (incremental, snapshot ou cdc), `chave_primaria` e
     `coluna_atualizacao`.
   - Veja se a estrutura cabe na limpeza padrão. Se não couber (ex.: data só numa linha
     separadora, cabeçalho em várias linhas), vai precisar de `silver_<nome>.sql`.

2. **Propor e esperar a aprovação.** Mostre:
   - o bloco YAML completo da fonte, com `colunas` (nome padronizado com prefixo da
     classe da informação, `origem`, `descricao` para o dicionário de dados, tipo,
     formatos, caixa, de-para, máscara; só o que for declarado entra na silver) e `regras`
     (nao_nulo, valores_aceitos, expressao, unico), cada regra com `drop` ou `alerta` e o
     motivo. Em snapshot e cdc, cada coluna da chave precisa de `nao_nulo` com `drop`;
   - toda coluna que o perfil marcou como sensível com `mascarar` (a sugestão do perfil);
   - uma tabela de-para das colunas: nome na origem → nome padronizado → tipo;
   - se vai criar `silver_<nome>.sql` e o que ele fará;
   - se há gold nova ou alterada (e a view `gold_vw_*` que o painel lê, com a máscara nas
     colunas sensíveis);
   - com `historico: true`, a `silver_<nome>` já é a SCD tipo 2 (não existe
     `silver_<nome>_historico`) e o retrato do snapshot é privado do pipeline.

   **Pare aqui e espere meu OK.**

3. **Aplicar:**
   - acrescente a fonte em `config/fontes.yml`, seguindo os comentários do arquivo;
   - se precisar, crie `src/pipeline/silver_<nome>.sql` com
     `CREATE TEMPORARY VIEW silver_int_<nome>_preparada` lendo `bronze_<nome>` (com os
     nomes de coluna da origem; os padronizados vêm do YAML), marque
     `preparacao_sql: true` e inclua o arquivo nas `libraries` de `resources/pipeline.yml`;
   - gold nova ou alterada: use a skill `novo-indicador`;
   - tipo tabela: use em `nome_completo` o nome real da tabela (`catalogo.schema.tabela`).
     Não há schema de origem no pacote nem tabela de origem no `setup/`; no Free Edition,
     só faça uma fonte `tabela` se o João criar a tabela fictícia e pedir.
   - cada camada tem o seu schema (`<projeto>_bronze`, `<projeto>_silver`, `<projeto>_gold`):
     não escreva nome de schema fixo; a bronze e a silver saem do `fontes.yml`, e a gold
     usa `${schema_gold}` e `${schema_silver}`.

4. **Atualizar o resto:** testes específicos em `tests/test_projeto.py` (quando houver
   lógica nova), `docs/arquitetura.md` (fontes, tabelas geradas e regras),
   `CHANGELOG.md` (seção `[Unreleased]`) e `docs/roteiro-de-operacao.md` (onde
   colocar o arquivo e as novas regras da aba Data quality, em linguagem não técnica).

5. **Validar e mostrar o resultado:** rode `ruff check .`, `pytest -q` e
   `databricks bundle validate -t dev` e mostre a saída. Deploy e execução em dev só com
   o meu OK (skill `implantar-dev`).

**Pronto quando:** a fonte está no YAML com descrição e regras, as colunas sensíveis têm
`mascarar`, e lint, testes e validate estão verdes.
