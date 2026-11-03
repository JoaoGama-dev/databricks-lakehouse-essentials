# Evals das skills

Skill também precisa de teste. Cada caso aqui tem uma entrada fictícia e uma lista de
verificações sobre a resposta esperada do Claude. **O CI não chama o modelo**: a
avaliação é manual e o CI só garante que os casos estão completos e que o perfil dos
arquivos fictícios detecta os dados sensíveis (`tests/test_claude_config.py`).

| Caso | Skill | O que exercita |
| --- | --- | --- |
| `novo-cliente/` | `novo-cliente` | clínica com CPF, telefone, linha de total, valor brasileiro, segunda fonte do tipo tabela |
| `nova-fonte/` | `nova-fonte` | admissões incrementais com CPF, salário brasileiro e junção frágil com a agenda |

Todos os dados são inventados (CPFs nas faixas `111.222.333-xx` e `222.333.444-xx`,
telefones `41 90000-xxxx`).

## Como rodar

1. Abra uma conversa nova no Claude Code (`/clear`), na raiz do projeto.
2. Cole o pedido do arquivo `pedido.md` do caso.
3. Leia a resposta e marque cada item de `verificacoes.md`.
4. O caso passa com todos os itens obrigatórios marcados. Se falhar, ajuste a skill (o
   `SKILL.md`), e não o eval, e rode de novo.
5. Registre o resultado no pull request que alterou a skill: caso, data, modelo e itens
   que falharam.

## Quando rodar

- Sempre que um `SKILL.md` de `novo-cliente` ou `nova-fonte` mudar.
- Ao trocar o modelo padrão do Claude Code.
- Antes de usar a skill no primeiro projeto real de um cliente.
