# Verificações: nova-fonte (admissões fictícias)

Marque cada item ao revisar a resposta do Claude. O caso passa com todos os itens
**obrigatórios** marcados.

## Obrigatórios

- [ ] Analisou o arquivo só com `scripts/perfilar_dados.py`; não leu as linhas do CSV.
- [ ] Nenhum nome, CPF ou salário individual aparece na resposta.
- [ ] `modo_carga: incremental`, com justificativa (arquivo só com as novidades).
- [ ] `cpf` e `nome_colaborador` com `mascarar: hash` (ou fora da silver, justificado).
- [ ] Colunas com prefixos e `descricao`: `dt_admissao`, `nm_colaborador`,
      `nr_cpf` ou `cd_cpf`, `nm_vaga`, `vl_salario`, `st_admissao`.
- [ ] `dt_admissao` com `formatos: ["yyyy-MM-dd"]` e regra `nao_nulo` com `drop`.
- [ ] Status com `mapa_valores` (Admitido, admitido, ADMITIDO, Desistiu, desistiu,
      Em análise) e regra `valores_aceitos` com `alerta`.
- [ ] O salário em formato brasileiro foi apontado: o tipo `decimal` atual não converte
      `3.200,50`; propôs uma solução (opção no YAML ou preparação SQL) antes de usar.
- [ ] Apontou o risco da junção com a agenda por nome (homônimos, nome mascarado na
      silver) e propôs uma chave melhor ou a junção antes do mascaramento.
- [ ] Terminou pedindo aprovação, sem alterar arquivos.

## Desejáveis

- [ ] Propôs o indicador na gold (ex.: `qt_admitidos` por vaga e mês) com a skill
      `novo-indicador`.
- [ ] Sugeriu ADR para a decisão sobre o formato numérico brasileiro.
