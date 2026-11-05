# 0019. Silver única em SCD tipo 2, com o retrato privado do pipeline

- **Status:** aceita
- **Data:** 2026-11-04

## Contexto

No snapshot com histórico, o pipeline criava três tabelas por fonte: o retrato
(`silver_int_<fonte>_retrato`), a silver atual (SCD tipo 1) e a silver histórica
(`silver_<fonte>_historico`, SCD tipo 2). A silver atual era só a versão vigente do
histórico, e o retrato era um passo interno que aparecia no catálogo sem ter uso fora do
pipeline. O ADR 0008 criou o histórico e o ADR 0009 pôs as regras no retrato.

## Decisão

1. **Uma só silver por fonte com `historico: true`: `silver_<fonte>` em SCD tipo 2**
   (`__START_AT` e `__END_AT`; a versão vigente tem `__END_AT` vazio). Saem a
   `silver_<fonte>_historico` e a silver atual separada.
2. **O retrato é uma materialized view privada** (`private=True`): existe só dentro do
   pipeline e não aparece no catálogo. As **expectations ficam nele**, porque o AUTO CDC
   FROM SNAPSHOT ignora as regras de views (ADR 0009, regra 6 do `CLAUDE.md`). Os números
   da aba Data quality e do `mon_qualidade_diaria` continuam sob o nome do retrato.
3. **Quem precisa do estado atual filtra `__END_AT IS NULL`.** A gold faz isso.
4. **Desempate do retrato** (complementa o ADR 0016): data de referência, depois
   `_ingerido_em`, `_modificado_em` e o nome do arquivo. O `_modificado_em` entra como
   coluna técnica da bronze.
5. Os avisos `arquivo_ignorado` e `codificacao_invalida` acham o arquivo do retrato pelas
   **versões vigentes da silver**, já que o retrato não está no catálogo.
6. **Tipo da tabela:** a `silver_<fonte>` com histórico tem `'tipo' = 'historico'`.
   A trava `pipelines.reset.allowed = false` continua nela (ADR 0017).

## Alternativas consideradas

- **Manter a silver atual e o histórico:** duplica o dado e cria dois nomes para a mesma
  coisa, sem ganho para o negócio.
- **Publicar o retrato:** o catálogo mostraria uma tabela intermediária que ninguém deve
  ler, e ela exigiria permissão e dicionário próprios.
- **Tirar as regras do retrato:** o AUTO CDC FROM SNAPSHOT as ignoraria sem aviso (ADR 0009).

## Consequências

- Menos tabelas e um só nome para a silver; o histórico responde "quando mudou" sem lógica
  extra.
- Quem só quer o estado atual precisa lembrar do filtro `__END_AT IS NULL`; a gold e a
  checagem `unico` já o aplicam.
- O retrato privado não pode ser consultado nem recebe tag; o diagnóstico passa pelo event
  log e pela silver. Se a Databricks mudar o suporte a tabelas privadas com AUTO CDC FROM
  SNAPSHOT, o plano B é publicar o retrato (`RETRATO_PRIVADO` em `config_fontes.py`).
- Os totais conferidos na integração são os mesmos do ADR 0008: depois da v2, 234 versões
  vigentes e 252 versões no total, 18 delas fechadas (v1: 227 vigentes, nenhuma fechada).
- Atualiza o [ADR 0008](0008-snapshot-com-auto-cdc-e-scd2.md) (a silver é uma só) e o
  [ADR 0009](0009-expectations-em-tabela-intermediaria.md) (o retrato é privado).
