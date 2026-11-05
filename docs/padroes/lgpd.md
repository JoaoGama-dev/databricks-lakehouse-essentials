# Dados reais, LGPD e o que o modelo pode ver

## Onde ficam os dados

- **Dados reais de clientes** ficam em `data/privado/`, ignorado pelo Git e pelo bundle.
  Nunca vão para o repositório nem para o workspace de dev.
- **Dados fictícios** são os únicos versionados: `data/agenda_exemplo_v*.csv`, gerados
  por `data/gerar_dados_exemplo.py`.
- **O Free Edition roda só dados fictícios.** Dados reais rodam apenas no ambiente Azure
  do cliente, na assinatura dele. O Free Edition é uma conta pessoal fora do contrato e do
  controle do cliente: levar dados pessoais para lá seria um tratamento sem base legal
  ([ADR 0010](../adr/0010-free-edition-so-com-dados-ficticios.md)).
- A Logos atua como **operadora** dos dados, seguindo as instruções do cliente, com acordo
  de confidencialidade assinado antes do diagnóstico.

## O que o modelo (Claude) pode ver

- **Perfil, nunca amostra.** Para entender um arquivo do cliente, o Claude roda
  `python scripts/perfilar_dados.py data/privado/<arquivo>` e trabalha só com a saída:
  estrutura, tipos, padrões de formato (`99/99/9999`, `Aa+ Aa+`), nulos e colunas
  sensíveis. Valores só aparecem em colunas não sensíveis de baixa cardinalidade.
- Nunca escreva nomes, telefones ou outros dados reais em README, comentários, testes,
  mensagens de commit ou exemplos.

## O que garante isso (guardrails)

| Camada | O que bloqueia |
| --- | --- |
| `.claude/settings.json` (deny) | `Read` de `.env*`, `data/privado/**`, `data/tabela_*`, `.databricks/**` |
| `proteger_arquivos.py` | `Read`, `Edit`, `Write` e `Grep` em qualquer planilha real de `data/` e em `.env*` |
| `proteger_comandos.py` | comandos que citam planilhas reais, `data/privado/` ou `.env`, mesmo dentro de uma mensagem de commit |

O hook de comandos é rígido de propósito: se uma mensagem de commit precisar citar um
caminho de dados, escreva a mensagem num arquivo e use `git commit -F`.

## Mascaramento

Quatro defesas, decididas nos ADRs 0002 e 0020
(`docs/adr/0002-dados-pessoais-no-unity-catalog.md` e
`docs/adr/0020-exemplo-sem-cargos-e-view-que-mascara.md`):

1. **`sensivel: true`** no `fontes.yml` em toda coluna com dado pessoal. Toda coluna com
   `mascarar` precisa dela (a validação recusa o contrário).
2. **Mascaramento fixo na silver**: `mascarar` no `fontes.yml` (`telefone` deixa DDD e 4
   últimos dígitos; `hash` usa sha256). O dado completo nem chega à silver.
3. **Máscara de coluna na gold**: toda coluna sensível da fato declara
   `MASK ${catalogo}.${schema_silver}.mascarar_dado_pessoal`. Só o grupo
   `grupo_dados_pessoais` vê o valor; os demais veem `****`. A função é criada pela tarefa
   `preparar_governanca` do job, no schema `<projeto>_silver` (máscaras só podem ser declaradas
   na definição da tabela do pipeline; `ALTER ... SET MASK` é recusado).
4. **A view da gold aplica a mesma função** nas colunas sensíveis
   (`gold_vw_entrevistas`: `nm_candidato` e `nr_telefone`), no padrão dynamic view. Não há
   garantia documentada de que o `MASK` da fato valha para quem lê por uma view, e o painel
   lê só a view. Coluna sensível nova na gold precisa do `MASK` na fato **e** da função na
   view; testes conferem.

Além disso, a tarefa `publicar_monitoramento` aplica a tag `pii` = `true` nas colunas
sensíveis da silver, da fato e da view, para localizar todo dado pessoal pelo
`information_schema.column_tags`. O retrato privado do pipeline não está no catálogo e não
recebe tag.

## Motivo da falha: no log e no e-mail

O texto de erro do motor pode trazer o registro que violou uma regra (nome, telefone). Por
isso ele **nunca é gravado nem enviado como está**. O `motivo_seguro` é uma lista de
permissões: deixa passar só o nome da regra do `fontes.yml`, a classe do erro e a etapa, com
300 caracteres no máximo. Esse motivo vai para:

- `mon_log_execucao` e a view `mon_falhas` (coluna do motivo);
- o e-mail do alerta `falha_carga`, enviado na hora pela `avisar_falha` e às 7h;
- o log legível da tarefa `publicar_monitoramento`.

A mensagem da tarefa `encerrar_com_falha` é um texto fixo, sem dado. O log legível só leva
nomes de tarefa, schema e tabela, status, contagens, datas e durações (ADR 0021 e 0022).

## Nome de arquivo e monitoramento

As views `mon_*` e a tabela `mon_log_execucao` não guardam dado pessoal. Os avisos `arquivo_ignorado` e
`codificacao_invalida` de `mon_estrutura` mostram **só o nome do arquivo** recebido.
Por isso o nome do arquivo nunca pode ter nome, CPF, telefone ou outro dado pessoal:
use datas e códigos (`agenda_2025-12-15.csv`).

## Retenção e exclusão de titular

A landing e a bronze de snapshot guardam o arquivo inteiro, com dado pessoal. A política de
retenção e o passo a passo para atender o pedido de um titular (com o script
`scripts/gerar_exclusao_titular.py`) estão em
[`retencao-e-exclusao.md`](retencao-e-exclusao.md).

## Quem acessa o quê

O modelo de acesso está no ADR 0018 (que substitui em parte o 0001) e em
`resources/governanca.yml`: cada camada tem o seu schema. A engenharia acessa todos
(`<projeto>_bronze`, com a landing, `<projeto>_silver`, `<projeto>_gold` e
`<projeto>_monitoramento`); o negócio lê apenas `<projeto>_gold`. Os grupos são variáveis do
bundle (`grupo_engenharia`, `grupo_leitura_gold`, `grupo_dados_pessoais`).
