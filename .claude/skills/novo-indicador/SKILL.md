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
   - arquivo novo em `src/pipeline/` entra sozinho (o pipeline lê a pasta inteira): não
     mexa em `resources/pipeline.yml`;
   - se a tabela tem coluna sensível, a view `src/views/gold_vw_*.sql` aplica a máscara.
   Só a camada do projeto muda (`docs/padroes/nucleo-e-projeto.md`): `gold_*.sql`,
   `gold_vw_*.sql`, `src/dashboards/negocio.lvdash.json` e `tests/projeto/`. Não edite o
   núcleo.
5. **Testar:** o contrato em `tests/nucleo/test_contrato_do_projeto.py` já cobre nomes,
   prefixos, tipos, descrições e máscara da gold; acrescente um teste em `tests/projeto/`
   se houver regra nova (ex.: os valores possíveis de uma situação).
6. **Painel:** se o indicador aparece no painel, atualize
   `src/dashboards/negocio.lvdash.json` lendo só da view da gold. O painel de saúde é do
   núcleo: não mexa nele.
7. **Validar:** rode e mostre `ruff check .`, `pytest -q` e `databricks bundle validate -t dev`.
   Rode também `pytest tests/nucleo/test_contrato_do_projeto.py tests/nucleo/test_nucleo_sem_projeto.py -q`
   e leia o que o contrato diz que não conseguiu verificar (ex.: máscara em expressão
   que deriva de coluna sensível).

**Pronto quando:** o indicador está na gold com descrição em toda coluna, só a camada do
projeto mudou, os testes (inclusive o contrato e o vazamento de `tests/nucleo`) e o
validate passam, e (se for o caso) o painel usa a coluna nova.
