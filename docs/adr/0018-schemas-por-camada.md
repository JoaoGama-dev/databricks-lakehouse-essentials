# 0018. Um schema por camada no mesmo catálogo

- **Status:** aceita
- **Data:** 2026-11-04

## Contexto

O ADR 0001 separou o projeto em dois schemas: `<projeto>` (landing, bronze, silver e
`mon_*`) e `<projeto>_gold`. Isso protegia o negócio, mas misturava no mesmo schema o dado
bruto, o dado limpo e o monitoramento, que têm públicos diferentes. Também havia um schema
`<projeto>_origem`, só para simular sistemas de origem no Free Edition. Sem uma fonte
`tabela` no exemplo, ele deixou de ter uso.

## Decisão

1. **Quatro schemas por projeto, no mesmo catálogo**, criados pelo bundle
   (`resources/governanca.yml`):
   - `<projeto>_bronze`: `bronze_<fonte>` e o volume `landing`;
   - `<projeto>_silver`: `silver_<fonte>` e a função `mascarar_dado_pessoal`;
   - `<projeto>_gold`: `gold_fato_*`, `gold_dim_*` e as views `gold_vw_*`;
   - `<projeto>_monitoramento`: o event log `mon_log_eventos`, `mon_falhas` e as views
     `mon_*`.
2. **Permissões:** a engenharia tem `ALL_PRIVILEGES` nos quatro. O grupo de leitura do
   negócio só lê a gold (`USE_SCHEMA` e `SELECT`). Em dev, o prefixo continua sendo
   `dev_<usuário>_`.
3. **O schema `<projeto>_origem` e o `setup` dele saem.** O setup cria só o catálogo.
4. O pipeline tem a silver como schema padrão. A bronze, a gold e o event log são
   publicados com o nome completo, pelas variáveis `schema_bronze`, `schema_gold` e
   `schema_monitoramento`.

## Alternativas consideradas

- **Manter dois schemas (ADR 0001):** protege o negócio, mas deixa bruto, limpo e
  monitoramento juntos. Qualquer permissão futura mais fina (por exemplo, abrir só a silver
  para um analista) exigiria mover tabelas.
- **Um catálogo por camada:** isolaria ainda mais, mas multiplica as external locations e
  os grants no cliente, sem ganho para o tamanho dos projetos do pacote.
- **Um schema só e `GRANT` por tabela:** já rejeitada no ADR 0001.

## Consequências

- Cada camada tem o seu público: bronze e silver só da engenharia, gold para o negócio,
  monitoramento só da engenharia.
- Quem lê a gold continua sem enxergar bronze, silver nem monitoramento, por construção.
- A função de máscara fica no schema da silver; quem usa `MASK` ou a view da gold cita esse
  schema (ADR 0020).
- Um ambiente que já existe **não migra sozinho**: os schemas e o volume antigos são
  recursos do bundle com outro nome. Veja o passo a passo (`unbind`) em
  [`levando-ao-azure.md`](../levando-ao-azure.md).
- Em dev, os dados vivem em quatro schemas `dev_<usuário>_<projeto>_<camada>`.
- Substitui em parte o [ADR 0001](0001-modelo-de-acesso-no-unity-catalog.md): valem a
  declaração no bundle, o `prevent_destroy`, os grupos e o volume só para a engenharia; o
  desenho de dois schemas deixa de valer.
