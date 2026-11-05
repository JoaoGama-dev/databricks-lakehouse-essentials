# 0001. Modelo de acesso no Unity Catalog

- **Status:** aceita, substituída em parte por [0018](0018-schemas-por-camada.md) (os dois
  schemas viraram um por camada; o resto continua valendo)
- **Data:** 2026-11-03

## Contexto

Até a Fase 2, o schema do projeto, o volume da landing e as permissões eram criados à mão
por um script de setup, e bronze, silver e gold ficavam no mesmo schema. O usuário de
negócio que lê o painel precisa da gold, mas não deve ver a bronze (dado bruto, com dado
pessoal sem máscara) nem as tabelas intermediárias (`silver_int_*`). No Unity Catalog, o
`SELECT` dado no schema vale para todas as tabelas dele.

## Decisão

1. **Schemas, volume e permissões são declarados no bundle** (`resources/governanca.yml`)
   e criados no `databricks bundle deploy`, com `prevent_destroy` para um `destroy` nunca
   apagar dados. O setup fica só com o catálogo do pacote e as origens simuladas.
2. **Dois schemas por projeto, separados pelo público:**
   - `<projeto>`: bronze e silver, só a engenharia (`ALL_PRIVILEGES`);
   - `<projeto>_gold`: gold, com `USE_SCHEMA` e `SELECT` para o grupo de leitura.
   O pipeline publica a silver no schema padrão e a gold no schema gold.
3. **Grupos como variáveis do bundle:** `grupo_engenharia`, `grupo_leitura_gold` e
   `grupo_dados_pessoais`. Em prod, os grupos do cliente; no Free Edition, o próprio
   usuário e o grupo nativo `account users` (o único leitor possível ali).
4. **Volume `landing` só para a engenharia** (`READ_VOLUME`, `WRITE_VOLUME`). Em prod ele
   é externo, sobre o ADLS do cliente, e o caminho é sempre `/Volumes/...` nos dois
   ambientes.
5. **Isolamento por desenvolvedor em dev:** o modo development prefixa os schemas com
   `dev_<usuário>_`; o código usa `${resources.schemas.*.name}`, nunca o nome fixo.

## Alternativas consideradas

- **Um schema só, com `GRANT SELECT` tabela por tabela na gold:** exigiria um script
  imperativo depois de cada carga (as tabelas do pipeline são recriadas e novas tabelas
  gold apareceriam sem permissão até alguém rodar o script). Rejeitada: o grant por
  schema é declarativo, fica no bundle e cobre automaticamente toda tabela gold nova.
- **Views de leitura num schema à parte, sobre a gold:** duplica objetos e exige manter
  uma view por tabela. Rejeitada pelo mesmo motivo.
- **Desligar o prefixo de dev (`presets.name_prefix`):** manteria o schema antigo, mas
  tiraria também o prefixo do job e do pipeline e misturaria o trabalho de dois
  desenvolvedores no mesmo schema. Rejeitada.

## Consequências

- Quem lê a gold não enxerga bronze nem silver, por construção.
- Uma tabela gold nova herda a leitura automaticamente; uma tabela que não deva ser lida
  pelo negócio não pode ir para o schema gold.
- O catálogo é do pacote, não do projeto: o `USE CATALOG` do grupo de leitura fica no
  setup (dev) ou na configuração do cliente (prod).
- Em dev, os dados vivem em `dev_<usuário>_<projeto>`; trocar de usuário significa
  recarregar os dados fictícios.
