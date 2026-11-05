# Decisões de arquitetura (ADRs)

Cada decisão de arquitetura do pacote Essentials fica registrada num arquivo
`NNNN-titulo.md`, com contexto, decisão, alternativas e consequências (formato da skill
`adr`, em `.claude/skills/adr/SKILL.md`). Uma decisão nova recebe o próximo número; uma
decisão que muda de ideia não é apagada: o ADR antigo passa a "substituída por NNNN".

Os ADRs 0001 a 0005 nasceram durante as Fases 3 a 5 do plano; os 0006 a 0013 registram,
depois, decisões tomadas antes (por isso trazem a data da decisão e a do registro); os
0014 e 0015 são da Fase 7, e os 0016 e 0017 vêm da rodada de testes por risco. Os 0018 a
0020 são da simplificação do exemplo: eles atualizam ou substituem em parte decisões
antigas, que trazem a relação no próprio status.

| Nº | Decisão | Status |
| --- | --- | --- |
| [0001](0001-modelo-de-acesso-no-unity-catalog.md) | Modelo de acesso no Unity Catalog: gold em schema próprio para o negócio | aceita, substituída em parte por 0018 |
| [0002](0002-dados-pessoais-no-unity-catalog.md) | Dados pessoais: máscara de coluna na gold e tags `pii` | aceita, atualizada por 0020 |
| [0003](0003-monitoramento-fora-do-pipeline.md) | Monitoramento em views fora do pipeline, sobre o event log publicado | aceita, atualizada por 0018 |
| [0004](0004-ingestao-so-com-fonte.md) | Tarefas de ingestão só quando há fonte do tipo | aceita |
| [0005](0005-testes-de-integracao.md) | Testes de integração num target `ci` isolado, destruído ao fim | aceita, atualizada por 0018 e 0020 |
| [0006](0006-sem-dbt-pipelines-declarativos.md) | Sem dbt: Lakeflow Spark Declarative Pipelines | aceita |
| [0007](0007-acelerador-orientado-por-metadados.md) | Acelerador orientado por metadados (`config/fontes.yml`) | aceita |
| [0008](0008-snapshot-com-auto-cdc-e-scd2.md) | Snapshot com AUTO CDC e histórico SCD tipo 2 | aceita, atualizada por 0019 |
| [0009](0009-expectations-em-tabela-intermediaria.md) | Expectations em tabela intermediária, nunca na view do AUTO CDC | aceita, atualizada por 0019 |
| [0010](0010-free-edition-so-com-dados-ficticios.md) | Free Edition só com dados fictícios | aceita |
| [0011](0011-deploy-de-producao-por-oidc.md) | Deploy de produção só pelo GitHub Actions, com OIDC | aceita |
| [0012](0012-guardrails-do-claude-code.md) | Guardrails determinísticos para o uso de IA (Claude Code) | aceita |
| [0013](0013-cadeia-de-suprimentos.md) | Cadeia de suprimentos: versões fixas, actions por SHA e varredura de segredos | aceita |
| [0014](0014-mudanca-na-origem-e-volume.md) | Mudança na origem e queda de volume avisam, sem parar a carga | aceita |
| [0015](0015-aviso-de-falha-com-motivo.md) | Aviso de falha com o motivo, sem dado pessoal | aceita |
| [0016](0016-data-de-referencia-do-snapshot.md) | Data de referência do snapshot: o retrato é o arquivo mais recente pelo conteúdo ou pelo nome, não pela ingestão | aceita, complementada por 0019 |
| [0017](0017-retencao-e-exclusao-de-titular.md) | Retenção e exclusão de titular: reset bloqueado e SQL gerado para revisão | aceita |
| [0018](0018-schemas-por-camada.md) | Um schema por camada no mesmo catálogo | aceita |
| [0019](0019-silver-unica-scd2-com-retrato-privado.md) | Silver única em SCD tipo 2, com o retrato privado do pipeline | aceita |
| [0020](0020-exemplo-sem-cargos-e-view-que-mascara.md) | Exemplo sem cargos nem agregada, com área por de-para e view que aplica a máscara | aceita |
