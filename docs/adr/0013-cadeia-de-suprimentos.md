# 0013. Cadeia de suprimentos: versões fixas, actions por SHA e varredura de segredos

- **Status:** aceita
- **Data:** 2026-11-03

## Contexto

O CI e o deploy de produção executam código de terceiros: actions do GitHub, pacotes do
PyPI no pipeline e nos jobs, ferramentas de lint e de varredura. Uma tag de action pode
ser movida para outro código, uma dependência sem versão muda sozinha entre duas
execuções, e versões recém-publicadas são o alvo mais comum de pacotes comprometidos.
O repositório é público, então um segredo commitado vaza na hora.

## Decisão

1. **Actions fixadas pelo SHA do commit**, com a versão num comentário.
2. **Dependências do Databricks com versão fixa num único arquivo**,
   `requirements-runtime.txt`, instalado pelo pipeline e pelo job com `-r`; o
   `requirements-dev.txt` o inclui e acrescenta as ferramentas de desenvolvimento.
3. **Dependabot** semanal para actions e pip, com **cooldown de 14 dias**: só propõe
   versões publicadas há pelo menos duas semanas. Cada atualização passa por PR e CI.
4. **gitleaks** no CI (job `segredos`, obrigatório) pelo binário oficial conferido pelo
   SHA-256 da release, e no **pre-commit**, na mesma versão.
5. **Permissões mínimas** nos workflows: `permissions: {}` no topo e cada job declarando
   só o que usa.

## Alternativas consideradas

- **Versões nas variáveis do bundle:** o Dependabot não as atualizaria.
- **Action do gitleaks:** mais uma dependência com Node e licença para organizações; o
  binário conferido por hash é mais simples de auditar.
- **Atualizar para a versão mais nova assim que sai:** expõe o projeto justamente na
  janela em que pacotes comprometidos costumam ser descobertos.

## Consequências

- Atualizar exige trocar versão e SHA (ou SHA-256) no lugar certo; os testes conferem
  que a versão do gitleaks é a mesma no CI e no pre-commit.
- Uma correção urgente numa dependência espera o cooldown ou exige exceção explícita
  (foi o caso da CLI v1.22.0 na Fase 5, contornado sem exceção: ADR 0005).
- Segredos são barrados antes do commit e de novo no PR.
