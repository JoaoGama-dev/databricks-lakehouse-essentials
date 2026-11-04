# 0017. Retenção e exclusão de titular

- **Status:** aceita
- **Data:** 2026-11-04

## Contexto

A landing e a bronze de um snapshot guardam o arquivo inteiro, com dado pessoal, para
sempre. A LGPD (art. 18) dá ao titular o direito de pedir a exclusão. Duas coisas
atrapalham: um full refresh apagaria o histórico SCD2 (que não se reconstrói) e reingeriria
a landing; e excluir de verdade, no Delta, exige mais que um `DELETE` (deletion vectors e
time travel mantêm o dado legível). Excluir à mão, de memória, é arriscado.

## Decisão

1. **`pipelines.reset.allowed = false`** na bronze de arquivo, banco e API e no histórico
   SCD2. O full refresh do grafo inteiro é recusado pelo Databricks antes de apagar qualquer
   coisa (o histórico depende do retrato, que seria recriado; confirmado na integração em
   2026-11-04). Para reprocessar, use `--full-refresh` só nas tabelas que podem ser recriadas.
2. **`scripts/gerar_exclusao_titular.py`** gera o SQL de exclusão para **revisão humana**.
   Não executa nada, não usa rede e recebe o titular só como parâmetro nomeado
   (`:titular_<coluna>`), com guarda contra parâmetro vazio e comparação por campo inteiro.
3. Passos: landing; bronze (um `UPDATE` que tira só as linhas do titular do texto bruto);
   silver e histórico (`DELETE`); aviso sobre streaming; atualização normal do pipeline;
   `REORG TABLE ... APPLY (PURGE)`; `VACUUM DRY RUN`; `VACUUM` depois do prazo
   (`delta.deletedFileRetentionDuration`, 7 dias; histórico da tabela
   `delta.logRetentionDuration`, 30 dias).
4. A política e o procedimento ficam em
   [`docs/padroes/retencao-e-exclusao.md`](../padroes/retencao-e-exclusao.md). Referência:
   <https://docs.databricks.com/aws/en/ldp/gdpr>.

## Alternativas consideradas

- **Full refresh para "limpar" a bronze:** apagaria o histórico SCD2 e reingeriria a
  landing; por isso foi bloqueado.
- **Script que executa a exclusão:** um erro apaga dados de outras pessoas sem revisão.
- **Pseudonimizar o titular em vez de apagar:** a bronze guarda o texto bruto; não
  atende ao pedido de exclusão.
- **Apagar o arquivo inteiro da landing e da bronze:** apagaria também as outras pessoas
  do arquivo e, no snapshot, o retrato voltaria a um arquivo antigo que também cita o titular.

## Consequências

- Mudar o **schema da bronze** passa a exigir procedimento manual: remover a propriedade
  `pipelines.reset.allowed` com decisão registrada, fazer a mudança e restaurá-la
  (ver [`camadas.md`](../padroes/camadas.md)).
- **Pendência:** as fontes `incremental` e `cdc` leem a bronze em streaming sem
  `skipChangeCommits` (`src/pipeline/silver.py`). Hoje o `UPDATE` ou `DELETE` na bronze
  quebraria a próxima carga delas. A agenda (snapshot) não tem esse problema. Antes de
  usar o roteiro nessas fontes, a opção precisa entrar no código.
- A política de reter só os últimos N dias da landing e da bronze **ainda não é
  automatizada**; é um próximo passo.
- A exclusão só termina depois do `VACUUM`; o chamado fica aberto até lá.
