# Roteiro de operação: painel de entrevistas

Este guia é para quem acompanha o painel no dia a dia e não precisa saber programar.
Ele explica de onde vêm os números, como conferir se estão atualizados e o que fazer
quando algo dá errado.

## 1. Como os dados chegam

O painel junta duas informações:

- **Agenda de entrevistas**: a planilha do RH, salva como **CSV** (separado por `;`).
  Cada envio é a **planilha inteira**; o painel sempre usa a versão mais recente.
- **Cadastro de cargos**: uma tabela que diz a qual **área** cada vaga pertence (por
  exemplo, tudo o que começa com "auxiliar de cozinha" é da área Cozinha).

Todos os dias às **6h** (horário de Brasília), uma carga automática lê o que chegou de
novo e atualiza o painel. No caminho, os dados passam por três etapas:

- **bronze**: cópia fiel do que chegou;
- **silver**: limpeza (nomes padronizados, status unificado, datas corrigidas,
  telefone mascarado) e regras de qualidade;
- **gold**: tabelas prontas para o painel, já com a área de cada vaga.

O histórico de mudanças de status fica guardado: dá para saber, por exemplo, quando
uma entrevista passou de Pendente para Aprovado.

## 2. Como ver se a carga rodou

1. Entre no Databricks e clique em **Jobs & Pipelines** no menu à esquerda.
2. Abra o job **essentials_portfolio_carga_diaria**.
3. A execução mais recente deve estar com o ícone verde (**Succeeded**). Vermelho
   (**Failed**) significa que a carga falhou.

Avisos automáticos por e-mail:

| Aviso | Quando | Quem recebe |
|---|---|---|
| Falha da carga | a execução termina com erro | o e-mail cadastrado no job |
| Carga demorada | a execução passa de 15 minutos (o normal é menos de 6) | o e-mail cadastrado no job |
| Carga atrasada | às 9h, se a última carga concluída tem mais de 26 horas (inclusive quando o job nem rodou) | o usuário responsável no workspace |

As tarefas **ingestao_banco** e **ingestao_api** aparecem como **Excluded** (puladas)
quando o projeto não tem fonte desse tipo. Isso é normal e não custa nada.

### Painel "Saúde da plataforma" (equipe de engenharia)

Em **Dashboards**, abra **Essentials · portfolio · Saúde da plataforma**. Ele mostra:

- horas desde a última carga e se alguma tabela está atrasada;
- por dia e regra, quantas linhas foram descartadas e quantos alertas houve;
- o custo diário do job e do pipeline, pelo preço de lista.

O painel só abre para a equipe de engenharia: as tabelas `mon_*` ficam no schema do
projeto, fechado para os usuários de negócio.

## 3. Como ver os registros descartados (aba Data quality)

1. Em **Jobs & Pipelines**, abra o pipeline **essentials_portfolio**.
2. No desenho do fluxo, clique em **silver_int_agenda_retrato** (ou
   **silver_int_cargos_retrato**, para o cadastro de cargos).
3. Abra a aba **Data quality**.

| Regra | O que acontece | Significado |
|---|---|---|
| `nome_preenchido` | linha **descartada** | entrevista sem nome do candidato |
| `data_entrevista_valida` | linha **descartada** | entrevista sem data |
| `status_conhecido` | entra, com **alerta** | status escrito de um jeito que o sistema não reconhece |
| `telefone_valido` | entra, com **alerta** | telefone vazio, incompleto ou corrompido pelo Excel (ex.: `4,19E+10`) |
| `horario_valido` | entra, com **alerta** | horário vazio ou fora do formato `09:30` |
| `id_cargo_preenchido` | cargo **descartado** | cargo sem identificador |
| `prefixo_preenchido` | cargo **descartado** | cargo sem o começo do nome da vaga |
| `area_conhecida` | entra, com **alerta** | área fora da lista combinada |
| `prefixo_unico` | **alerta** | o mesmo prefixo cadastrado duas vezes (aparece em **silver_int_cargos_unico_ds_prefixo_vaga**) |

Alertas não impedem a carga, mas indicam algo a corrigir na planilha ou no cadastro.

A aba Data quality mostra uma atualização por vez. O histórico, dia a dia, fica na view
`mon_qualidade_diaria` do schema do projeto e no painel "Saúde da plataforma" (seção 2).

## 4. Vagas "Não classificada"

Quando o nome de uma vaga não combina com nenhum cargo do cadastro, ela aparece no
painel com a área **Não classificada**. Para corrigir, peça a inclusão do cargo no
cadastro (o começo do nome da vaga e a área). Na carga seguinte, as entrevistas dessa
vaga passam para a área certa, inclusive as antigas.

## 5. O que fazer se a carga falhar

1. **Não apague nem altere tabelas manualmente.** Toda mudança passa pelo processo de
   implantação.
2. Confira se o último arquivo enviado está correto: salvo como CSV separado por `;`,
   no mesmo formato da planilha de sempre (linhas `AGENDA DIA dd/mm/aaaa` e as
   entrevistas abaixo).
3. Se o arquivo estava errado, envie uma versão corrigida **com outro nome** e aguarde a
   próxima carga, ou peça ao suporte para rodar a carga na hora.
4. Se o arquivo estava certo, acione o suporte (seção 8) com o horário da falha e um
   print da tela da execução.

## 6. Como enviar a planilha manualmente

1. No Databricks, clique em **Catalog** no menu à esquerda.
2. Navegue até o catálogo do projeto (`prd` no Azure), o schema do projeto (por exemplo,
   `portfolio`), o volume `landing` e a pasta `agenda` (no Azure, o volume fica no
   contêiner `landing`, pasta `portfolio/agenda`; também dá para enviar pelo portal do
   Azure ou pelo Azure Storage Explorer). Só a equipe de engenharia pode enviar arquivos.
3. Clique em **Upload to this volume** e escolha o arquivo.
4. Use sempre um **nome novo**, por exemplo com a data: `agenda_2025-12-15.csv`. Um
   arquivo com nome repetido não é lido de novo.
5. O painel é atualizado na próxima carga das 6h.

## 7. Como acompanhar o custo no Azure

O consumo de nuvem é pago diretamente à Microsoft, na assinatura da empresa.

1. Entre no **portal do Azure** (portal.azure.com).
2. Abra **Gerenciamento de Custos** > **Análise de custo** e filtre pelo grupo de
   recursos do projeto.
3. Em **Orçamentos**, confira o teto mensal combinado no diagnóstico. Avisos automáticos
   são enviados ao atingir **80%** e **100%** do teto.

Se o custo subir sem motivo aparente (sem aumento de dados), avise o suporte.

### Relatório mensal de custo do projeto (equipe de engenharia)

O consumo da Databricks fica nas tabelas de sistema de faturamento. A view
`mon_custo_diario`, no schema do projeto, já filtra o job e o pipeline do projeto pelos
IDs deles. Para o relatório do mês anterior, rode num SQL warehouse (troque `<catálogo>`
e `<schema>` pelos do projeto, por exemplo `prd` e `portfolio`):

```sql
SELECT date_trunc('MONTH', dt_uso) AS dt_mes, nm_recurso, ds_produto,
  round(sum(qt_dbus), 2) AS qt_dbus, round(sum(vl_custo_lista), 2) AS vl_custo_lista,
  first(sg_moeda) AS sg_moeda
FROM <catálogo>.<schema>.mon_custo_diario
WHERE dt_uso >= add_months(date_trunc('MONTH', current_date()), -1)
  AND dt_uso < date_trunc('MONTH', current_date())
GROUP BY ALL
ORDER BY nm_recurso, ds_produto;
```

O valor é o **preço de lista**, sem os descontos do contrato. Para somar outros recursos
do mesmo cliente, filtre `system.billing.usage` pelas tags `projeto`, `cliente` e
`ambiente`, que o bundle coloca no job e no pipeline. No faturamento **serverless**, a
documentação da Databricks garante as tags só por uma **política de uso serverless**
(*serverless usage policy*, antes chamada *budget policy*) com essas tags, criada pelo
administrador da conta e aplicada ao job **e** ao pipeline: o pipeline disparado pelo job
não herda a política do job.

## 8. O que significa cada coluna (dicionário de dados)

Toda tabela usada pelo painel tem a descrição de cada coluna, em português.

1. No Databricks, clique em **Catalog** no menu à esquerda.
2. Abra o catálogo do projeto (`prd` no Azure), o schema da gold (por exemplo,
   `portfolio_gold`) e a tabela (por exemplo, `gold_fato_entrevista`).
3. Na aba **Columns**, a coluna **Comment** explica cada campo.

O nome e o telefone do candidato são dados pessoais: aparecem como `****` para quem não
faz parte do grupo de dados pessoais. Para ter acesso, peça ao responsável pelos acessos
da empresa.

O nome da coluna também ajuda: o começo indica o tipo de informação.

| Começo | Significa | Exemplo |
|---|---|---|
| `dt_` | data | `dt_entrevista` |
| `hr_` | hora | `hr_entrevista` |
| `nm_` | nome | `nm_candidato` |
| `st_` | status ou situação | `st_entrevista` |
| `qt_` | quantidade | `qt_entrevistas` |
| `fl_` | sim ou não | `fl_compareceu` |
| `id_` | identificador | `id_cargo` |

## 9. Quando acionar o suporte

| Situação | Severidade |
|---|---|
| A carga falhou ou o painel principal não atualiza | Crítica |
| Um indicador usado em decisão está errado | Crítica |
| Muitas linhas descartadas de repente na aba Data quality | Alta |
| Painel lento ou alerta de qualidade que se repete | Média |
| Dúvida de uso, novo cargo no cadastro, mudança de cor ou rótulo | Baixa |

Ao abrir o chamado pelo e-mail de suporte do contrato, informe: o que aconteceu, desde
quando, o nome do arquivo envolvido e um print da tela. O atendimento é em dias úteis,
das 9h às 18h (horário de Brasília).
