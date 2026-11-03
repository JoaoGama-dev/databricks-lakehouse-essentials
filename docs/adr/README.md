# Decisões de arquitetura (ADRs)

Cada decisão de arquitetura do pacote Essentials fica registrada num arquivo
`NNNN-titulo.md`, com contexto, decisão, alternativas e consequências (formato da skill
`adr`, em `.claude/skills/adr/SKILL.md`). Uma decisão nova recebe o próximo número; uma
decisão que muda de ideia não é apagada: o ADR antigo passa a "substituída por NNNN".

Os ADRs 0001 a 0005 nasceram durante as Fases 3 a 5 do plano; os 0006 a 0013 registram,
depois, decisões tomadas antes (por isso trazem a data da decisão e a do registro).

| Nº | Decisão | Status |
| --- | --- | --- |
| [0001](0001-modelo-de-acesso-no-unity-catalog.md) | Modelo de acesso no Unity Catalog: gold em schema próprio para o negócio | aceita |
| [0002](0002-dados-pessoais-no-unity-catalog.md) | Dados pessoais: máscara de coluna na gold e tags `pii` | aceita |
| [0003](0003-monitoramento-fora-do-pipeline.md) | Monitoramento em views fora do pipeline, sobre o event log publicado | aceita |
| [0004](0004-ingestao-so-com-fonte.md) | Tarefas de ingestão só quando há fonte do tipo | aceita |
| [0005](0005-testes-de-integracao.md) | Testes de integração num target `ci` isolado, destruído ao fim | aceita |
| [0006](0006-sem-dbt-pipelines-declarativos.md) | Sem dbt: Lakeflow Spark Declarative Pipelines | aceita |
| [0007](0007-acelerador-orientado-por-metadados.md) | Acelerador orientado por metadados (`config/fontes.yml`) | aceita |
| [0008](0008-snapshot-com-auto-cdc-e-scd2.md) | Snapshot com AUTO CDC e histórico SCD tipo 2 | aceita |
| [0009](0009-expectations-em-tabela-intermediaria.md) | Expectations em tabela intermediária, nunca na view do AUTO CDC | aceita |
| [0010](0010-free-edition-so-com-dados-ficticios.md) | Free Edition só com dados fictícios | aceita |
| [0011](0011-deploy-de-producao-por-oidc.md) | Deploy de produção só pelo GitHub Actions, com OIDC | aceita |
| [0012](0012-guardrails-do-claude-code.md) | Guardrails determinísticos para o uso de IA (Claude Code) | aceita |
| [0013](0013-cadeia-de-suprimentos.md) | Cadeia de suprimentos: versões fixas, actions por SHA e varredura de segredos | aceita |
