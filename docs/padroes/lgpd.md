# Dados reais, LGPD e o que o modelo pode ver

## Onde ficam os dados

- **Dados reais de clientes** ficam em `data/privado/`, ignorado pelo Git e pelo bundle.
  Nunca vão para o repositório nem para o workspace de dev.
- **Dados fictícios** são os únicos versionados: `data/agenda_exemplo_v*.csv`, gerados
  por `data/gerar_dados_exemplo.py`.
- **O Free Edition roda só dados fictícios.** Dados reais rodam apenas no ambiente Azure
  do cliente, na assinatura dele.

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

- Toda coluna que o perfil marcar como sensível recebe `mascarar` no `fontes.yml`
  (`telefone` deixa DDD e 4 últimos dígitos; `hash` usa sha256).
- A silver e a gold só têm o dado mascarado. A bronze guarda o dado bruto e deve ter
  acesso restrito à equipe técnica (Fase 3 do plano: grants como código).
