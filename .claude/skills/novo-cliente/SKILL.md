---
name: novo-cliente
description: Use quando eu pedir para adaptar o projeto a um novo cliente a partir dos arquivos CSV ou da lista de tabelas dele
---

# Começar um novo projeto do pacote Essentials

O objetivo é montar o projeto do cliente seguindo a estrutura do pacote (catálogo
`essentials`, um schema por camada, bundle `essentials_<projeto>`) e propor fontes,
regras e indicadores **antes de alterar qualquer arquivo**. Regras de LGPD em
`docs/padroes/lgpd.md`.

1. **Definir o nome do projeto** em snake_case (ex.: `clinica_vida`). Ele vira os schemas
   `essentials.<projeto>_bronze`, `_silver`, `_gold` e `_monitoramento`, o bundle
   `essentials_<projeto>`, o job `<projeto>_job_carga_diaria`, o pipeline
   `<projeto>_pipeline_medalhao` e o repositório `essentials-<projeto>`.

2. **Levantar as fontes pelo perfil, nunca pelo conteúdo.**
   - Arquivos do cliente: ficam em `data/privado/` (ignorado pelo Git e bloqueado pelos
     hooks). Para cada um, rode `python scripts/perfilar_dados.py data/privado/<arquivo>`
     e use **exclusivamente** a saída: separador, codificação, linhas estruturais (totais,
     separadores), tipos, padrões de formato, nulos e colunas sensíveis. Não leia o
     arquivo de outro jeito. Excel: peça ao usuário para salvar como CSV (UTF-8).
   - Lista de tabelas (ERP, banco, Unity Catalog): anote colunas, tipos, chave e uma
     coluna crescente para carga incremental, sem pedir amostra de linhas.
   - APIs: URL, autenticação, onde fica a lista de registros e a paginação.

3. **Propor, sem alterar nada:**
   - **Fontes**: uma tabela com nome, tipo, modo de carga (e por quê), chave primária,
     coluna de atualização e se precisa de `silver_<fonte>.sql`;
   - **de-para de colunas** por fonte: nome na origem → nome padronizado com prefixo da
     classe da informação (`id_ cd_ nm_ ds_ sg_ st_ nr_ qt_ vl_ pc_ dt_ dh_ hr_ fl_`) → tipo;
   - **o `config/fontes.yml` completo** proposto;
   - **regras de qualidade** por fonte, cada uma com `drop` ou `alerta` e o motivo (em
     snapshot e cdc, `nao_nulo` com `drop` em cada coluna da chave);
   - **dados pessoais**: toda coluna que o perfil marcou como sensível, com `mascarar`;
   - **modelo da gold** em estrela: `gold_fato_*` e, quando houver cadastro de apoio,
     `gold_dim_*`, mais a view `gold_vw_*` que o painel lê (com a máscara nas colunas
     sensíveis e o que depende de hoje). Agregações ficam no painel, não numa `gold_agg_*`,
     salvo decisão registrada. 3 a 6 indicadores que respondem às perguntas do negócio e as
     junções entre fontes (sem função não determinística na materialized view);
   - **riscos**: dados insuficientes, chaves que não batem entre fontes, fontes que
     exigem acesso externo (banco e api só funcionam no Azure).

   **Pare aqui e espere meu OK.** Ajuste a proposta quantas vezes eu pedir.

4. **Aplicar, depois do OK:**
   - no `databricks.yml`, `bundle.name: essentials_<projeto>` e o `default` da variável
     `projeto`;
   - o `setup/00_setup_free_edition.sql` não leva o nome do projeto (cria só o catálogo);
     não há schema de origem a criar;
   - substitua `config/fontes.yml`;
   - crie os `src/pipeline/silver_<fonte>.sql` necessários e remova os do projeto anterior;
   - substitua os `src/pipeline/gold_*.sql` e as views `src/views/gold_vw_*.sql` (skill
     `novo-indicador`);
   - atualize as `libraries` de `resources/pipeline.yml`;
   - ajuste os testes que citam fontes ou colunas pelo nome (`agenda`,
     `dt_entrevista`...) em `tests/test_projeto.py`;
   - atualize `README.md` (nome do projeto e exemplo), `docs/arquitetura.md` (fontes,
     tabelas e regras), `CLAUDE.md` e `docs/roteiro-de-operacao.md`.

5. **Lembrar dos dados reais**: confira que os arquivos do cliente estão em
   `data/privado/` e fora do Git antes de qualquer commit, e que dados reais só vão para
   o ambiente do cliente, nunca para o Free Edition.

6. **Validar e mostrar o resultado:** rode `ruff check .`, `pytest -q` e
   `databricks bundle validate -t dev` e mostre a saída. Deploy e execução em dev só com
   o meu OK, e só com dados fictícios (skill `implantar-dev`).

**Pronto quando:** a proposta foi aprovada, aplicada, e lint, testes e validate estão
verdes.
