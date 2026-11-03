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

Três camadas, decididas no ADR 0002 (`docs/adr/0002-dados-pessoais-no-unity-catalog.md`):

1. **`sensivel: true`** no `fontes.yml` em toda coluna com dado pessoal. Toda coluna com
   `mascarar` precisa dela (a validação recusa o contrário).
2. **Mascaramento fixo na silver**: `mascarar` no `fontes.yml` (`telefone` deixa DDD e 4
   últimos dígitos; `hash` usa sha256). O dado completo nem chega à silver.
3. **Máscara de coluna na gold**: toda coluna sensível da gold declara
   `MASK ${catalogo}.${schema_projeto}.mascarar_dado_pessoal`. Só o grupo
   `grupo_dados_pessoais` vê o valor; os demais veem `****`. A função é criada pela tarefa
   `governanca_antes` do job (máscaras só podem ser declaradas na definição da tabela do
   pipeline; `ALTER ... SET MASK` é recusado).

Além disso, a tarefa `governanca_depois` aplica a tag `pii` = `true` nas colunas
sensíveis da silver e da gold, para localizar todo dado pessoal pelo
`information_schema.column_tags`.

## Quem acessa o quê

O modelo de acesso está no ADR 0001 e em `resources/governanca.yml`: a bronze, a silver e
a landing ficam no schema do projeto, só da engenharia; o negócio lê apenas o schema
`<projeto>_gold`. Os grupos são variáveis do bundle (`grupo_engenharia`,
`grupo_leitura_gold`, `grupo_dados_pessoais`).
