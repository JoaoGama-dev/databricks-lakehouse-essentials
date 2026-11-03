# Política de segurança

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use o reporte privado do GitHub:

1. Na página do repositório, abra a aba **Security**.
2. Clique em **Report a vulnerability**.
3. Descreva o problema, como reproduzir e o impacto que você vê.

O reporte fica visível só para o mantenedor. A primeira resposta vem em até 5 dias
úteis, com a avaliação e o próximo passo.

## O que entra no escopo

- Segredos, tokens ou credenciais expostos no código ou no histórico.
- Dados pessoais no repositório (o projeto só deve conter dados fictícios).
- Falhas no CI/CD que permitam alterar produção sem aprovação.
- Brechas nos guardrails do Claude Code (`.claude/settings.json` e `.claude/hooks/`)
  que permitam ler dados reais ou rodar comandos de produção.

## Como o projeto se protege

- Varredura de segredos (gitleaks) em todo pull request e no pre-commit.
- Actions fixadas por SHA e dependências com versão fixa, atualizadas pelo Dependabot.
- Deploy de produção só pelo workflow, com login OIDC e aprovação do environment `prod`.
- Dados reais de clientes nunca no repositório (`docs/padroes/lgpd.md`).
