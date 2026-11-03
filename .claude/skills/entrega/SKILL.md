---
name: entrega
description: Use quando eu pedir para preparar a entrega de um projeto ao cliente - roteiro de operação com os nomes do projeto, checklist de acessos, dicionário de dados, treinamento e aceite.
---

# Preparar a entrega ao cliente

Gera os documentos de entrega em `docs/entrega/`, em linguagem para quem não é técnico.

1. **Roteiro de operação:** revise `docs/roteiro-de-operacao.md` com os nomes reais do
   projeto (catálogo, schema, job, pipeline, painel, pastas da landing) e as regras de
   qualidade da aba Data quality.
2. **Dicionário de dados:** exporte com a consulta da seção "Dicionário de dados" de
   `docs/arquitetura.md` e salve como `docs/entrega/dicionario-de-dados.md` (tabela, coluna, tipo,
   descrição), só para silver e gold.
3. **Checklist de acessos** (`docs/entrega/checklist-de-acessos.md`):
   - [ ] grupos e permissões no Unity Catalog (leitura só na gold para o negócio);
   - [ ] acessos da Logos com credenciais individuais, revogáveis pelo cliente;
   - [ ] secret scope e conexões criados pelo cliente;
   - [ ] repositório no GitHub do cliente, com a `main` protegida;
   - [ ] alertas de orçamento (Azure Budgets) configurados.
4. **Treinamento** (`docs/entrega/treinamento.md`): roteiro da sessão de 2 h
   (painel, aba Data quality, envio de arquivo, o que fazer se a carga falhar, suporte).
5. **Aceite** (`docs/entrega/termo-de-aceite.md`): o que foi entregue (fontes, tabelas,
   painel, documentação), critérios de aceite combinados e campo para a assinatura do
   ponto focal; o início da garantia conta a partir dessa data.
6. **Conferir:** nenhum dado real nos documentos; todos os nomes batem com o
   `databricks.yml` e o `config/fontes.yml`.

**Pronto quando:** os cinco documentos existem em `docs/entrega/`, revisados, sem dado real.
