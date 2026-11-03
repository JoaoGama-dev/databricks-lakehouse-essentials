---
name: novo-indicador
description: Use quando eu pedir um indicador, KPI, métrica ou tabela nova na gold, ou uma mudança no modelo estrela (dimensão, fato ou agregada).
---

# Novo indicador na gold

Padrões em `docs/padroes/nomes.md` e `docs/padroes/camadas.md`.

1. **Entender a pergunta de negócio.** Escreva em uma frase o que o indicador responde,
   a fórmula (numerador, denominador, filtro) e a granularidade (por dia, mês, área...).
2. **Escolher onde ele mora:**
   - atributo de cadastro → `gold_dim_<nome>`;
   - evento ou fato do negócio, uma linha por evento → `gold_fato_<nome>`;
   - total pronto para o painel → `gold_agg_<nome>`.
   Prefira acrescentar coluna a uma tabela existente a criar tabela nova.
   Regra de negócio (ex.: classificar uma situação) fica na gold, nunca no painel.
3. **Propor e esperar meu OK:** a tabela, as colunas novas com prefixo, tipo e descrição,
   e o SQL. **Pare aqui.**
4. **Implementar** em `src/pipeline/gold_*.sql`:
   - lista de colunas com tipo e `COMMENT`, na ordem do `SELECT`;
   - `COMMENT` da tabela e `TBLPROPERTIES ('camada' = 'gold', 'tipo' = ...)`;
   - arquivo novo entra nas `libraries` de `resources/pipeline.yml`.
5. **Testar:** os testes de `tests/test_projeto.py` já cobrem nomes, tipos e descrições;
   acrescente um teste se houver regra nova (ex.: os valores possíveis de uma situação).
6. **Painel:** se o indicador aparece no painel, atualize `src/dashboards/*.lvdash.json`
   lendo só da gold.
7. **Validar:** rode e mostre `ruff check .`, `pytest -q` e `databricks bundle validate -t dev`.

**Pronto quando:** o indicador está na gold com descrição em toda coluna, os testes e o
validate passam, e (se for o caso) o painel usa a coluna nova.
