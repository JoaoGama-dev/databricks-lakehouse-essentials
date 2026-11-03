# 0004. Tarefas de ingestão só quando há fonte do tipo

- **Status:** aceita
- **Data:** 2026-11-03

## Contexto

O job diário tem duas tarefas de ingestão serverless (`ingestao_banco` e `ingestao_api`)
que trazem bancos externos e APIs para a landing. Num projeto só com arquivos e tabelas,
como o de exemplo, elas subiam todo dia apenas para dizer que não havia nada a fazer:
computação ociosa paga.

O bundle não lê o `fontes.yml` na hora do deploy, então não dá para incluir ou tirar as
tarefas a partir dele.

## Decisão

1. Variáveis `ingerir_banco` e `ingerir_api` (`"true"` ou `"false"`) no `databricks.yml`.
2. Antes de cada ingestão, uma **tarefa de condição** (`condition_task`, que não usa
   computação) compara a variável com `"true"`. A ingestão depende do resultado `"true"`;
   com `"false"`, ela aparece como **pulada** (*Excluded*) e não custa nada.
3. `atualizar_lakehouse` usa `run_if: NONE_FAILED`: roda com as ingestões puladas, mas
   não se alguma delas falhar.
4. **Um teste confere que as variáveis refletem o `fontes.yml`**: incluir uma fonte
   `banco` sem trocar `ingerir_banco` para `"true"` quebra o CI.

## Alternativas consideradas

- **Tarefa Python que lê o `fontes.yml` e decide:** ela mesma seria uma tarefa serverless
  diária, o custo que se queria evitar.
- **Arquivo de recurso opcional por tipo de fonte:** o `include` do bundle não é
  condicional; seria preciso apagar ou criar arquivos por projeto, sem teste que pegue o
  esquecimento.

## Consequências

- Uma informação existe em dois lugares (`fontes.yml` e variáveis), mas o teste impede
  que divirjam.
- Validado em dev: com o `fontes.yml` atual, as duas ingestões aparecem como *Excluded* e
  o pipeline e a governança terminam com SUCCESS.
