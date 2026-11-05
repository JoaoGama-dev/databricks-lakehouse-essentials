# essentials_portfolio

Projeto do pacote Essentials: lakehouse medalhão orientado por metadados, empacotado como
Databricks Asset Bundle. Roda no Free Edition (target `dev`, só dados fictícios) e no
Azure Databricks do cliente (target `prod`). Tudo em português do Brasil.

## Onde está cada coisa

| O quê | Onde |
| --- | --- |
| Fontes do projeto (o que muda por cliente) | `config/fontes.yml` + `config/fontes.schema.json` |
| Lógica da config (sem Spark, testada) | `src/essentials/config_fontes.py` |
| Bronze e silver genéricas | `src/pipeline/bronze.py`, `src/pipeline/silver.py` |
| Lógica específica de uma fonte | `src/pipeline/silver_<fonte>.sql` |
| Gold (modelo estrela) | `src/pipeline/gold_*.sql` |
| Views da gold (o painel lê só elas; aplicam a máscara) | `src/views/gold_vw_*.sql` |
| Painel AI/BI | `src/dashboards/*.lvdash.json`, `resources/dashboard.yml` |
| Monitoramento (views `mon_*`, `mon_log_execucao`, log legível, alertas) | `src/essentials/monitoramento_sql.py`, `log_sql.py`, `log_texto.py`, `src/governanca/publicar_monitoramento.py`, `resources/alertas.yml` |
| Bundle, job e pipeline | `databricks.yml`, `resources/*.yml` |
| Perfil de dados sem expor conteúdo | `scripts/perfilar_dados.py` |
| Permissões e hooks do Claude Code | `.claude/settings.json`, `.claude/hooks/` |
| Subagentes e skills | `.claude/agents/`, `.claude/skills/` |
| Arquitetura, guias (Free Edition, Azure) e desenvolvimento | `docs/arquitetura.md`, `docs/guia-free-edition.md`, `docs/levando-ao-azure.md`, `docs/desenvolvimento.md` |
| Incidentes reais, defesas e testes | `docs/cenarios-reais.md` |
| Retenção e exclusão de titular (LGPD) | `docs/padroes/retencao-e-exclusao.md`, `scripts/gerar_exclusao_titular.py` |
| Decisões de arquitetura (ADRs) | `docs/adr/` (índice em `docs/adr/README.md`; skill `adr`) |
| Histórico de versões | `CHANGELOG.md` (anote em `[Unreleased]`) |
| Plano de evolução | `docs/plano-padrao-senior.md` |

## Padrões (leia antes de mudar o assunto correspondente)

- `docs/padroes/nomes.md`: tabelas `camada_tipo_nome` e colunas com prefixo (`dt_`, `nm_`...).
- `docs/padroes/camadas.md`: bronze, silver, AUTO CDC, expectations, gold, dicionário de dados.
- `docs/padroes/lgpd.md`: dados reais, mascaramento, o que o modelo pode ver.
- `docs/padroes/fluxo-de-trabalho.md`: branch, PR, validação, implantação, limitações.

## Regras inegociáveis

1. **Dados reais nunca no contexto.** Ficam em `data/privado/`; analise só pela saída de
   `scripts/perfilar_dados.py`. Nunca escreva dados reais em código, testes ou docs.
2. **Free Edition só com dados fictícios** (`data/agenda_exemplo_v*.csv`).
3. **Produção nunca por comando local**: só pelo workflow `deploy.yml`. Nada à mão em prod.
4. **Nunca na `main`**: branch + PR + CI verde. Sem push forçado.
5. **Sem dbt**; Python com `from pyspark import pipelines as dp`, nunca `import dlt`.
6. **Bronze sem transformação; qualidade só via expectations; expectations nunca em view
   que alimenta AUTO CDC.**
7. **Dicionário obrigatório**: toda coluna da silver e da gold com descrição; toda tabela
   com `COMMENT` e `TBLPROPERTIES ('camada', 'tipo')`.
8. **Nada fixo de ambiente ou projeto no código**: use as variáveis do `databricks.yml`.
9. **Não invente sintaxe**: confirme bundle com `databricks bundle schema` e Claude Code
   na documentação oficial; se não der, diga isso.

## Fluxo de uma mudança grande (subagentes em `.claude/agents/`)

`arquiteto-dados` (propõe) → **aprovação do João** → `engenheiro-dados` (implementa) →
`qa-dados` (valida; devolve ao engenheiro se falhar) → `revisor-seguranca` (revisa o diff)
→ `devops-dados` (implanta e roda em dev) → `documentador` → pull request → CI →
**aprovação do João** → merge. Produção só pelo workflow de deploy, nunca por agente.

## Antes de dizer que terminou

Rode e mostre a saída (liberados em `.claude/settings.json`):

```
ruff check .
pytest -q
databricks bundle validate -t dev
```

Deploy e execução em dev pedem confirmação; prod é bloqueado.
