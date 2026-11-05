# 0024. Integração em duas rodadas e desempate pela modificação do arquivo

- **Status:** aceita
- **Data:** 2026-11-05

## Contexto

A integração fazia nove cenários em sequência (v1, v2, v5, v6, v7, full refresh, v8, v3 e
v4), cada um com uma carga. Era demorada e gastava a cota diária do Free Edition.
O desempate do retrato usava a ordem de ingestão, que depende de como o Auto Loader divide
os arquivos em micro-batches: arquivos enviados juntos não tinham ordem garantida.

## Decisão

1. **Duas rodadas, cerca de 15 minutos** (timeout de 30), sem o input `cenarios_de_falha`:
   - rodada 1: v1;
   - rodada 2: v2, v6, v7 e v5 numa carga só. Esperado: retrato = v5, `arquivo_ignorado` =
     v2, v6 e v7, histórico de 252 versões, 234 vigentes e 18 fechadas, e o log com a
     última atualização anterior preenchida.
2. **Viram testes de unidade:** cp1252, full refresh, regra que para a carga e queda de
   volume. Os arquivos v3, v4 e v8 ficam em `data/` para teste manual no dev. Para forçar
   uma falha, envie a v4; para voltar, envie a v5 (cópia da v2).
3. **Desempate do retrato:** data de referência, depois **modificação do arquivo na
   landing**, depois ingestão e, por fim, nome. A ordem de envio vale, sem depender dos
   micro-batches.

## Alternativas consideradas

- **Manter os nove cenários:** custo e tempo altos; os riscos são cobertos por teste de
  unidade, que roda em todo PR.
- **Manter o desempate pela ingestão:** não é estável com vários arquivos na mesma carga.
- **Desempatar só pelo nome:** exige disciplina de quem envia.

## Consequências

- A integração cabe na cota e confere o que só o Databricks mostra (histórico SCD2,
  desempate, avisos e o log da carga).
- Copiar ou reenviar um arquivo muda a modificação dele: o mais recente vence o empate.
  Com o mesmo conteúdo, o histórico não ganha versão nova.
- Falha de ponta a ponta (job vermelho, e-mail) agora se vê só no teste manual no dev.
- Atualiza o [ADR 0005](0005-testes-de-integracao.md) e o
  [ADR 0016](0016-data-de-referencia-do-snapshot.md) (e o desempate do
  [ADR 0019](0019-silver-unica-scd2-com-retrato-privado.md)).
