## O que muda

<!-- Uma ou duas frases: o problema e a solução. -->

## Como foi validado

- [ ] `ruff check .` e `pytest -q` verdes
- [ ] `databricks bundle validate -t dev` OK
- [ ] Rodou em dev com os dados fictícios, quando mexe no pipeline, na gold ou no painel

## Checklist

- [ ] **Testes**: comportamento novo tem teste
- [ ] **Dicionário de dados**: coluna nova da silver com `descricao` no `fontes.yml`;
      coluna nova da gold com tipo e `COMMENT`
- [ ] **Nomes**: tabelas em `camada_tipo_nome` e colunas com prefixo (`docs/padroes/nomes.md`)
- [ ] **LGPD**: nenhum dado real em código, testes, docs ou commits; coluna sensível com
      `mascarar` (`docs/padroes/lgpd.md`)
- [ ] **Segurança**: nenhum segredo; actions por SHA; dependências com versão fixa
- [ ] **ADR**: decisão de arquitetura registrada em `docs/adr/`, quando houver
- [ ] **Documentação**: `docs/` (arquitetura, guias, roteiro de operação) atualizados quando
      mudar o uso; README só se mudar a visão geral
- [ ] **CHANGELOG**: mudança anotada em `[Unreleased]` no `CHANGELOG.md`
