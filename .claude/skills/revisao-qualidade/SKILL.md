---
name: revisao-qualidade
description: Use para revisar a qualidade de uma mudança no lakehouse antes do pull request - lint, testes, nomes, dicionário de dados, expectations e cobertura de testes. É o checklist do agente qa-dados.
---

# Revisão de qualidade

1. **Rodar e mostrar a saída:** `ruff check .`, `pytest -q` e
   `databricks bundle validate -t dev`. Qualquer falha é bloqueante.
2. **Ver o que mudou:** `git diff main...HEAD --stat` e o diff dos arquivos relevantes.
3. **Checklist** (marque cada item como ok, falha ou não se aplica):
   - [ ] Nomes de tabelas em `camada_tipo_nome` e colunas com prefixo da classe
         (`docs/padroes/nomes.md`).
   - [ ] Toda coluna nova da silver tem `descricao` no `fontes.yml`; toda coluna nova da
         gold tem tipo e `COMMENT`; toda tabela tem `COMMENT` e `TBLPROPERTIES`.
   - [ ] Toda coluna de chave em snapshot ou cdc tem regra `nao_nulo` com `drop`.
   - [ ] Nenhum `WHERE` escondendo problema de qualidade: o que é inválido sai por
         expectation, para ser contado.
   - [ ] Nenhuma expectation em view que alimenta AUTO CDC.
   - [ ] Colunas sensíveis com `mascarar`.
   - [ ] Comportamento novo tem teste; teste que só passa por acaso não conta.
   - [ ] Nada fixo de ambiente ou projeto no código (catálogo, schema, host, e-mail).
4. **Veredito** no formato:

```
VEREDITO: APROVADO | DEVOLVIDO
- [falha] arquivo:linha - o que está errado e o que fazer
- [ok] ...
```

**Pronto quando:** o veredito foi entregue com todos os itens do checklist avaliados.
