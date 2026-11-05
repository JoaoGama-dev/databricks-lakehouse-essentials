---
name: implantar-dev
description: Use quando eu pedir para implantar, fazer deploy ou rodar o projeto no Databricks de desenvolvimento (Free Edition) com os dados fictícios.
disable-model-invocation: true
---

# Implantar e rodar em dev

Só o target `dev` e só dados fictícios. Produção é bloqueada pelas permissões e pelos
hooks: não tente contornar.

1. **Pré-requisitos:** `ruff check .` e `pytest -q` verdes; login feito
   (`databricks auth login`); `BUNDLE_VAR_alert_email` definido na sessão.
2. **Validar:** `databricks bundle validate -t dev`.
3. **Implantar:** `databricks bundle deploy -t dev` (pede minha confirmação).
4. **Dados:** se a landing estiver vazia, gere com `python data/gerar_dados_exemplo.py`,
   crie a pasta (`databricks fs mkdir dbfs:/Volumes/essentials/<projeto>/landing/<fonte>`)
   e envie **só** `data/agenda_exemplo_v1.csv` (ou a v2, para testar a segunda carga).
5. **Rodar:** `databricks bundle run essentials_carga_diaria -t dev` (pede confirmação).
   Use `--full-refresh-all` no pipeline **só** com meu OK: ele apaga o histórico SCD 2.
6. **Ler o resultado:**
   - status do job (o comando mostra o link da execução);
   - contagem por camada (bronze, silver, gold) no SQL warehouse;
   - regras de qualidade: no pipeline, aba **Data quality** das tabelas
     `silver_int_*_retrato`, ou pelo event log
     (`event_log('<pipeline_id>')`, eventos `flow_progress` com `data_quality`).
7. **Se falhar, pare.** Mostre o erro, explique a causa e proponha a correção antes de
   alterar qualquer arquivo. Erros comuns:
   - pasta da landing não existe → `fs mkdir`;
   - catálogo inexistente → rodar `setup/00_setup_free_edition.sql` (os schemas e o volume
     são criados pelo próprio deploy);
   - deploy recusado por `prevent_destroy` ao mudar schema ou volume → não desligue a
     proteção; siga a migração com `unbind` de `docs/levando-ao-azure.md`;
   - mudança de schema em streaming table → avaliar com o usuário antes de full refresh;
   - 401 no CI → token do secret `DATABRICKS_TOKEN_DEV` expirado ou errado.

**Pronto quando:** o job terminou com SUCCESS e as contagens e as regras de qualidade
foram conferidas e relatadas.
