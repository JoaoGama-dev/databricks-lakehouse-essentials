# 0010. Free Edition só com dados fictícios

- **Status:** aceita
- **Data:** 2026-10-30 (registrada em 2026-11-03)

## Contexto

O desenvolvimento e o portfólio rodam no **Databricks Free Edition**, uma conta pessoal,
sem contrato com o cliente, sem os controles dele e com uso comercial proibido pelos
termos da Databricks. Os dados dos clientes (agenda de candidatos, por exemplo) têm nome
e telefone de pessoas: dados pessoais pela LGPD, que a Logos trata como operadora,
seguindo as instruções do cliente.

## Decisão

1. **Dados reais só no ambiente do cliente** (Azure Databricks, na assinatura dele),
   nunca no Free Edition nem no repositório.
2. No Free Edition e no Git, **só dados fictícios** do gerador
   (`data/gerar_dados_exemplo.py`, semente fixa), com o mesmo formato e a mesma sujeira da
   planilha real, mas nomes e telefones inventados.
3. `data/*.csv` fica no `.gitignore` (exceção: `agenda_exemplo_v*.csv`), o que também
   impede o bundle de enviar arquivos reais ao workspace. Arquivos do cliente ficam em
   `data/privado/`.
4. O modelo de IA nunca vê dados reais: analisa arquivos do cliente só pelo perfil de
   `scripts/perfilar_dados.py` (estrutura, sem valores sensíveis), com hooks que
   bloqueiam a leitura dos arquivos (ADR 0012).

## Alternativas consideradas

- **Amostra anonimizada do cliente no Free Edition:** ainda é tratamento de dado pessoal
  fora do ambiente do cliente, e a anonimização é difícil de garantir.
- **Desenvolver direto no workspace do cliente:** cada cliente pagaria pelo
  desenvolvimento e os testes de portfólio dependeriam de acessos de terceiros.

## Consequências

- O portfólio e o CI são públicos sem risco de vazamento.
- Fontes `banco` e `api` não são testadas no Free Edition (acesso externo restrito); só
  no Azure.
- O gerador precisa reproduzir os problemas reais (BOM, `;`, telefone convertido pelo
  Excel, status escritos de vários jeitos) para os testes valerem; os totais esperados
  dos testes de integração dependem da semente fixa.
