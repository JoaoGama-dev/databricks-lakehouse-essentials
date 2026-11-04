# 0014. Mudança na origem e queda de volume avisam, sem parar a carga

- **Status:** aceita
- **Data:** 2026-11-03

## Contexto

A sustentação do Essentials promete detectar no mesmo dia quando um sistema de origem
muda de estrutura, e regras de qualidade que "barram e avisam". Dois casos comuns não
tinham aviso:

- **Coluna nova na origem.** O Auto Loader rodava no modo padrão, `addNewColumns`: com
  uma coluna nova, a carga do dia **falha** e só volta na execução seguinte. Em fonte do
  tipo tabela, a coluna nova entrava na bronze sem ninguém saber.
- **Arquivo errado ou incompleto.** Um retrato que chega pela metade passa por todas as
  regras de linha e, no modo snapshot, apaga da silver o que sumiu do arquivo.

## Decisão

1. **Auto Loader em modo `rescue`** para CSV, JSON e Parquet: a carga nunca falha por
   coluna nova; os valores vão para `_rescued_data`. No Excel, o Auto Loader exige
   `schemaEvolutionMode` `none` (coluna nova é ignorada).
2. **View `mon_estrutura`**: colunas da bronze que o `fontes.yml` não conhece (fontes sem
   preparação e que não são texto) e linhas com `_rescued_data` na última carga. Cada
   linha é um aviso.
3. **View `mon_volume`**: linhas gravadas por carga, pelo event log (`num_output_rows`).
   No modo snapshot, alerta quando o retrato vem vazio ou cai mais que
   `limite_queda_volume_pct` (padrão 50%) em relação à carga anterior. No incremental e no
   cdc, zero linhas novas num dia é normal: a view só informa.
4. **Alerta SQL `qualidade_carga`** às 7h, com a tabela dos avisos no e-mail.
5. Coluna **removida** ou renomeada na origem continua quebrando a silver (o contrato
   exige a coluna): vira falha da carga, com o motivo (ADR 0015).

## Alternativas consideradas

- **Manter `addNewColumns`:** a falha avisa, mas tira o painel do ar por um dia por algo
  que a silver nem usa.
- **`failOnNewColumns`:** para a carga até alguém mexer; pior para um cliente pequeno.
- **Parar a carga por queda de volume:** um retrato menor pode ser legítimo (fim de
  ano, mudança de processo); o aviso deixa a decisão para quem conhece o negócio. Para
  arquivo claramente errado, há a ação `falhar` nas regras.

## Consequências

- A carga do dia continua com coluna nova; o ajuste no `fontes.yml` entra depois, pelo
  processo normal (até 4 horas por ocorrência na sustentação).
- O alerta de volume só existe no snapshot; um retrato vazio ainda apaga a silver, mas o
  aviso chega no mesmo dia e a carga seguinte com o arquivo certo restaura tudo.
- Testado nos cenários da integração: a v3 (só o último mês) e uma coluna nova na origem
  `cargos` disparam os avisos com a carga em SUCCESS.
