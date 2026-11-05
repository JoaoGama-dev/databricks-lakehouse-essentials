# 0008. Snapshot com AUTO CDC e histórico SCD tipo 2

- **Status:** aceita, atualizada por [0019](0019-silver-unica-scd2-com-retrato-privado.md)
  (com `historico: true`, a `silver_<fonte>` é a própria SCD tipo 2; não há mais
  `silver_<fonte>_historico`)
- **Data:** 2026-10-30 (registrada em 2026-11-03)

## Contexto

A fonte principal do exemplo, a agenda de entrevistas do RH, é uma planilha **reenviada
inteira** a cada vez: entrevistas mudam de status (de Pendente para Aprovado, por
exemplo) e o arquivo novo traz tudo de novo. O cliente quer o estado atual e também
saber quando cada entrevista mudou. Outras fontes podem mandar só o que é novo
(incremental) ou inclusões, alterações e exclusões (CDC).

## Decisão

O `fontes.yml` declara o **`modo_carga`** de cada fonte:

- `incremental`: a silver só acrescenta;
- `snapshot`: **AUTO CDC FROM SNAPSHOT** compara o retrato novo com o anterior;
- `cdc`: **AUTO CDC** aplica as mudanças, com coluna de operação e valor de exclusão.

Com `historico: true`, o pipeline cria também `silver_<fonte>_historico` em **SCD tipo
2** (`__START_AT` e `__END_AT`). A chave vem de `chave_primaria` e a ordem das versões de
`coluna_atualizacao`.

## Alternativas consideradas

- **Sobrescrever a silver a cada carga:** simples, mas perde o histórico de status.
- **`MERGE` escrito à mão:** repete o que o AUTO CDC já faz e é fácil errar a ordem das
  versões e as exclusões.
- **Guardar todos os retratos e calcular o histórico na gold:** cresce sem limite e
  joga para a gold uma lógica que é da silver.

## Consequências

- A silver mostra o estado atual e o histórico responde "quando mudou" sem lógica extra.
- Toda coluna da chave precisa de regra `nao_nulo` com `drop`: o AUTO CDC não aceita
  chave nula (a validação do `fontes.yml` exige).
- No snapshot, as regras de qualidade não podem ficar na view que alimenta o AUTO CDC
  (ADR 0009).
- Os totais do histórico são conferidos nos testes de integração (ADR 0005): 252 versões
  e 18 fechadas depois da v2 do exemplo.
