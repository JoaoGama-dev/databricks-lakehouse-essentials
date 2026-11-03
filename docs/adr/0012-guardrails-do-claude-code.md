# 0012. Guardrails determinísticos para o uso de IA (Claude Code)

- **Status:** aceita
- **Data:** 2026-11-03

## Contexto

O projeto é desenvolvido com o Claude Code, que lê arquivos e roda comandos. As regras
críticas (não ler dados reais, não implantar em produção, não fazer push na `main`)
existiam só como texto no `CLAUDE.md`, e um texto é uma instrução que o modelo pode
esquecer ou interpretar mal. Além disso, a skill de adaptar um cliente mandava ler
linhas do CSV real, o que punha dados pessoais no contexto do modelo.

## Decisão

**O que não pode falhar vira permissão ou hook; o que é orientação fica no `CLAUDE.md`
ou numa skill.**

1. **Permissões versionadas** em `.claude/settings.json`: libera lint, testes e
   `bundle validate`; pede confirmação para deploy, run, commit e push; nega produção,
   `destroy`, push forçado e leitura de `.env` e de dados reais.
2. **Hooks em Python**, só biblioteca padrão e com testes (`tests/test_hooks.py`):
   bloqueiam comandos de produção e destroy, push na `main`, menção a planilhas reais e
   impressão de tokens; impedem leitura e edição de dados reais; rodam o ruff em cada
   `.py` editado; restringem o que os subagentes de QA e documentação podem editar.
3. **Perfil, nunca amostra:** `scripts/perfilar_dados.py` mostra a estrutura de um
   arquivo do cliente sem valores sensíveis, e as skills analisam só essa saída.
4. **Subagentes com papéis e ferramentas mínimas** e um fluxo com aprovação humana antes
   de implementar e antes do merge (`docs/desenvolvimento.md`).

## Alternativas consideradas

- **Só instruções no `CLAUDE.md`:** dependem de o modelo seguir o texto; uma falha
  vaza dado ou implanta em produção.
- **Sandbox do Claude Code:** não roda no Windows nativo, onde o projeto é
  desenvolvido; fica registrado como limitação.
- **Não usar IA no desenvolvimento:** perderia a produtividade que permite a uma equipe
  enxuta manter vários projetos.

## Consequências

- Os bloqueios valem mesmo que o modelo erre, e cada um tem teste.
- Os hooks são rígidos de propósito: qualquer menção a planilha real é bloqueada,
  inclusive em mensagem de commit (use `git commit -F`), e qualquer texto com
  `bundle destroy` também.
- O `CLAUDE.md` fica enxuto, apontando para `docs/padroes/`.
- Evals manuais das skills críticas em `tests/evals/` (o CI não chama o modelo).
