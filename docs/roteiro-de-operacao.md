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

Se a carga falhar, quem está cadastrado no alerta recebe um **e-mail automático**.

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
2. Navegue até o catálogo `essentials`, o schema `portfolio`, o volume `landing` e a
   pasta `agenda` (no Azure, use o contêiner `landing`, pasta `portfolio/agenda`, pelo
   portal do Azure ou pelo Azure Storage
   Explorer).
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

## 8. Quando acionar o suporte

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
