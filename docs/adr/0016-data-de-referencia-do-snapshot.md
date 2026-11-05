# 0016. Data de referência do snapshot

- **Status:** aceita, complementada por [0019](0019-silver-unica-scd2-com-retrato-privado.md)
  (o desempate passa a ser data de referência, `_ingerido_em`, `_modificado_em` e nome do
  arquivo)
- **Data:** 2026-11-04

## Contexto

Numa fonte `snapshot` de arquivos, cada arquivo é um retrato completo e vale só o mais
recente. Até aqui, "mais recente" era o último arquivo **ingerido**. Isso erra quando o
arquivo chega fora de ordem: uma planilha antiga reenviada depois fazia o painel "voltar
no tempo". Também errava com um arquivo só com cabeçalho, que virava um retrato vazio.

## Decisão

1. A fonte snapshot de arquivo ganha o campo opcional **`data_referencia`**, com três
   tipos: `ingestao` (padrão, o comportamento antigo), `conteudo` (uma expressão SQL
   agregada sobre as colunas padronizadas, calculada por arquivo) e `nome_arquivo` (regex
   com um grupo e o formato da data).
2. O retrato é o arquivo com a **maior data de referência**. Data vazia fica por último;
   empate desempata pela ingestão mais recente e pelo nome do arquivo. Arquivo que não
   gerou linha nenhuma não entra na disputa.
3. A agenda usa `conteudo` com `max(dt_entrevista)`: a planilha do ano só cresce.
4. O arquivo recebido por último que não virou retrato aparece em `mon_estrutura` como
   **`arquivo_ignorado`**, coberto pelo alerta `qualidade_carga`. Texto do retrato que
   não é UTF-8 válido (`is_valid_utf8`) aparece como **`codificacao_invalida`** (típico de
   planilha salva em cp1252; o formato texto guarda os bytes como chegaram, sem trocar por
   U+FFFD, conferido no Free Edition em 2026-11-04): a orientação é salvar em UTF-8; o CSV aceita a opção `encoding` do Auto Loader.
5. Os avisos mostram **só o nome do arquivo**. Por isso o nome do arquivo nunca pode
   conter dado pessoal.

## Alternativas consideradas

- **Último arquivo ingerido (o que havia):** erra com arquivo fora de ordem.
- **Data de modificação do arquivo na landing:** muda quando alguém copia ou reenvia o
  arquivo; não diz nada sobre o conteúdo.
- **Obrigar um nome com data em todo arquivo:** depende de disciplina de quem envia; fica
  disponível como `nome_arquivo`, mas não como regra única.
- **Falhar a carga quando o arquivo é antigo:** impede o painel de atualizar por um erro
  que não é de dado; o aviso basta.

## Consequências

- Arquivo fora de ordem, reenvio e arquivo só com cabeçalho deixam de piorar o painel.
- A `expressao` de `conteudo` é **código executável** no pipeline: deve ser revisada como
  código no PR, como qualquer SQL.
- Se duas planilhas têm a mesma data máxima mas conteúdo diferente, vale a última
  ingerida. A escolha de `data_referencia` deve ser confirmada com o cliente.
- `codificacao_invalida` só detecta bytes que não formam UTF-8 válido; um texto que já
  chegou com os acentos trocados, mas em UTF-8 válido, passa.
- Cobertos pelos cenários v5 a v8 da integração (ver
  [`docs/cenarios-reais.md`](../cenarios-reais.md)).
