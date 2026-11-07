# Cenários reais e como o projeto se protege

Esta página liga cada incidente que acontece em produção à defesa do projeto e ao teste
que a mantém de pé.

## A regra dos testes

**Todo teste protege contra um risco real:** dado errado, vazamento de dado pessoal, custo
inesperado, deploy quebrado ou falha de segurança. Se um teste não consegue dizer qual
desses riscos ele evita, ele não deve existir.

Por isso a forma e a ordem dos ADRs e do CHANGELOG não são testadas: isso é papel da
revisão do PR. O único teste de documentação confere que nenhum link relativo está
quebrado (`tests/nucleo/test_documentacao.py`).

Os testes de unidade rodam no CI a cada PR (`pytest -q`). A integração roda no target `ci`
pelo workflow `integracao.yml`, em duas rodadas de carga (v1; depois v2, v6, v7 e v5 numa
carga só; [ADR 0024](adr/0024-integracao-em-duas-rodadas-e-desempate-pelo-arquivo.md)). Os
cenários de falha (v3, v4, v8, full refresh e coluna nova) são testes de unidade; os
arquivos v3, v4 e v8 ficam em `data/` para teste manual no dev (ver
[`desenvolvimento.md`](desenvolvimento.md)).

## Matriz de incidentes

Os testes citados como `test_carga` estão em `tests/projeto/integracao/test_carga.py` e rodam
só na integração; os demais, em `tests/nucleo/` (motor, contrato e proteções) ou
`tests/projeto/` (regras do exemplo), pelo nome do arquivo.

| Incidente real | Risco | Como o projeto se protege | Teste que cobre |
| --- | --- | --- | --- |
| **v3**: a planilha chega só com o último mês (queda de volume) | Painel perde quase todo o histórico e ninguém percebe | `mon_volume` compara o retrato com a carga anterior; o alerta `qualidade_carga` avisa às 7h. A carga não para ([ADR 0014](adr/0014-mudanca-na-origem-e-volume.md)) | `test_base_producao::test_volume_so_alerta_no_snapshot_com_retrato_vazio_ou_queda_acima_do_limite` |
| **Coluna nova** na origem (CSV, JSON ou Parquet) | Carga quebra, ou a coluna nova passa despercebida | Auto Loader em modo `rescue` guarda a coluna em `_rescued_data`; `mon_estrutura` mostra `coluna_nova`. É só teste de unidade: a agenda é lida como texto e não tem colunas da origem para comparar | `test_base_producao::test_coluna_nova_vira_aviso_em_mon_estrutura` e `test_base_producao::test_bronze_de_arquivo_nao_falha_com_coluna_nova` |
| **v4**: arquivo errado, com entrevista de 2019 | Dado errado vai para o painel | A regra `data_plausivel` tem ação `falhar`: a carga para e nada é gravado. A `publicar_monitoramento` grava o motivo em `mon_log_execucao`, a `avisar_falha` dispara o alerta `falha_carga` na hora e a `encerrar_com_falha` deixa o job vermelho ([ADR 0021](adr/0021-tarefa-final-de-monitoramento-e-aviso-de-falha-na-hora.md)) | `test_projeto::test_regra_data_plausivel_para_a_carga_inteira`, `test_config_fontes::test_regra_falhar_vira_expectation_que_para_a_carga` e `test_log::test_aviso_de_falha_sai_logo_depois_da_publicacao_e_o_job_fica_vermelho` |
| **v4**: o motivo da falha cita o registro | Nome ou telefone de uma pessoa vaza por e-mail | `motivo_seguro` guarda só o nome da regra; nunca o registro | `test_base_producao::test_motivo_de_regra_falhar_traz_so_os_nomes_das_regras`, `test_motivo_seguro_erros_reais::test_motivo_de_erro_real_nunca_carrega_o_valor_do_dado` e `test_log::test_log_de_tabela_nunca_grava_o_texto_do_erro_do_motor` |
| **v4**: depois da falha, a silver muda | Dado parcial no painel | Nada é gravado na carga que falha; a silver fica com a última carga boa | sem teste automático desde o [ADR 0024](adr/0024-integracao-em-duas-rodadas-e-desempate-pelo-arquivo.md); confira no dev com a v4 ([`desenvolvimento.md`](desenvolvimento.md)) |
| **Falha repetida pelo serverless** | A tarefa de monitoramento rodava 3 vezes e atrasava o aviso | `publicar_monitoramento` só termina com erro se uma etapa dela falhar (o bundle omite `max_retries: 0`, então a proteção está em não sair com erro à toa) | `test_log::test_publicar_monitoramento_roda_sempre_depois_de_tudo_e_nunca_de_novo`, `test_log::test_decisao_de_terminar_com_erro` e `test_log::test_erro_numa_etapa_da_publicacao_tambem_marca_o_job_como_falha` |
| **Nova falha no dia seguinte** | O alerta não avisa de novo enquanto a falha de ontem está nas 24 horas | `retrigger_seconds: 3600` no alerta `falha_carga` | `test_log::test_alerta_de_falha_avisa_de_novo_numa_nova_falha` |
| **Reenvio** (v5): o mesmo arquivo volta com outro nome | Versão falsa no histórico SCD2 | Empate na data de referência fica com o arquivo de modificação mais recente na landing; como o conteúdo é o mesmo, o histórico não ganha versão nova ([ADR 0024](adr/0024-integracao-em-duas-rodadas-e-desempate-pelo-arquivo.md)) | `test_carga::test_retrato_e_o_arquivo_esperado`, `test_carga::test_versoes_na_silver` e `test_config_fontes::test_silver_ordena_pela_data_de_referencia_e_desempata_sem_depender_da_ordem_de_chegada` |
| **Fora de ordem** (v6): a planilha antiga chega depois | O painel "volta no tempo" | `data_referencia` (agenda: `max(dt_entrevista)`) escolhe o retrato pela data, não pela ingestão; `mon_estrutura` avisa `arquivo_ignorado` ([ADR 0016](adr/0016-data-de-referencia-do-snapshot.md)) | `test_carga::test_retrato_e_o_arquivo_esperado`, `test_carga::test_avisos_de_estrutura_da_agenda` e `test_projeto::test_agenda_escolhe_o_retrato_pela_maior_data_de_entrevista` |
| **Só cabeçalho** (v7): arquivo sem nenhuma entrevista | Retrato vazio apaga o painel | Arquivo sem linhas não entra na disputa pelo retrato; `mon_estrutura` avisa `arquivo_ignorado` | `test_carga::test_avisos_de_estrutura_da_agenda` e `test_projeto::test_so_cabecalho_nao_tem_entrevista` |
| **cp1252** (v8): planilha salva fora do UTF-8 | Acentos trocados sem ninguém perceber (nomes errados) | `mon_estrutura` avisa `codificacao_invalida` quando o texto do retrato não é UTF-8 válido (`is_valid_utf8`); a carga não para. Orientação: salvar em UTF-8 | `test_base_producao::test_codificacao_invalida_olha_so_o_arquivo_do_retrato_da_fonte_texto` e `test_projeto::test_cp1252_e_a_v2_em_outra_codificacao` |
| **Full refresh** acidental | Histórico SCD2 (a `silver_agenda`) apagado e landing reingerida (custo) | `pipelines.reset.allowed = false` na bronze de arquivo e no histórico: o Databricks recusa o full refresh do grafo inteiro sem apagar nada ([ADR 0017](adr/0017-retencao-e-exclusao-de-titular.md)) | `test_config_fontes::test_bronze_da_landing_e_historico_nao_sao_esvaziados_por_full_refresh` e `test_log::test_pipeline_nunca_roda_com_full_refresh_pelo_job` |
| **Nome de arquivo com dado pessoal** | Os avisos mostram o nome do arquivo e o expõem | Avisos de arquivo mostram só o nome, sem a pasta; o nome nunca pode ter dado pessoal ([`docs/padroes/lgpd.md`](padroes/lgpd.md)) | `test_base_producao::test_avisos_de_arquivo_mostram_so_o_nome_do_arquivo` |
| **Chave nula** | O AUTO CDC recebe chave inválida | A regra `nao_nulo` da chave é gerada sozinha, com `drop` | `test_config_fontes::test_chave_sem_regra_ganha_nao_nulo_com_drop_sozinha` e, para a config de qualquer cliente, `test_contrato_do_projeto::test_coluna_da_chave_tem_nao_nulo_que_barra_a_linha` |
| **Telefone sem máscara** | Dado pessoal completo na silver | `mascarar: telefone` deixa só DDD e 4 últimos dígitos | `test_projeto::test_telefone_e_mascarado` |
| **Nome e telefone sem máscara na view do painel** | O `MASK` da fato pode não valer para quem lê por uma view; o negócio veria o dado pessoal | A view `gold_vw_entrevistas` aplica a função de máscara em toda coluna sensível ([ADR 0020](adr/0020-exemplo-sem-cargos-e-view-que-mascara.md)) | `test_contrato_do_projeto::test_coluna_sensivel_que_chega_a_gold_tem_mascara` (vale para a gold e a view de qualquer cliente; só pega `alias.coluna AS nome`, ver [`nucleo-e-projeto.md`](padroes/nucleo-e-projeto.md)) e `test_governanca::test_coluna_mascarada_precisa_ser_sensivel` |
| **UDF Python no código** | Perde o motor otimizado e o refresh incremental das materialized views | A lógica é toda em SQL e funções nativas; um teste recusa UDF em `src/` | `test_repositorio::test_codigo_nao_usa_udf_python` |
| **Painel lê a fato ou a bronze** | Dado pessoal fora da view mascarada | Os datasets do painel só leem `gold_vw_*`, sem catálogo fixo | `test_projeto::test_datasets_do_painel_so_leem_a_view_da_gold_sem_catalogo_fixo` |
| **Ingestão ociosa** | Custo de tarefa sem fonte | `condition_task` pula a ingestão de banco e API quando não há fonte do tipo ([ADR 0004](adr/0004-ingestao-so-com-fonte.md)); a variável `ingerir_fontes_externas` tem de refletir o `fontes.yml` | `test_contrato_do_projeto::test_variavel_de_ingestao_reflete_o_fontes_yml` e `test_pipeline_e_bundle::test_job_roda_ingestao_antes_do_pipeline` |
| **Custo de outro projeto ou ambiente na conta** | Custo errado e teto de custo que avisa à toa ou não avisa | A atribuição é pela tag `projeto` (dev, ci e prod), sem pegar projeto de nome parecido; o warehouse só entra se for dedicado ([ADR 0023](adr/0023-custo-do-projeto-por-tag-e-projecao.md)) | `test_monitoramento::test_custo_cobre_dev_ci_e_prod_do_projeto_em_qualquer_target`, `test_monitoramento::test_custo_nao_pega_outro_projeto_com_nome_parecido` e `test_monitoramento::test_warehouse_compartilhado_fica_fora_e_o_comentario_diz` |
| **Comando em produção, de máquina local** | Mudança manual e sem rastro em prod | `.claude/settings.json` nega `-t prod` e os hooks bloqueiam o comando; produção só pelo `deploy.yml` ([ADR 0012](adr/0012-guardrails-do-claude-code.md)) | `test_hooks::test_comandos_perigosos_sao_bloqueados` e `test_claude_config::test_negacoes_essenciais_existem` |
| **Dado pessoal no perfil do arquivo** | O modelo vê nome ou telefone reais | `scripts/perfilar_dados.py` mostra só estrutura e formato | `test_perfilar_dados::test_perfil_nao_expoe_nomes_nem_telefones` |
| **Exclusão de titular com parâmetro vazio** | Um campo em branco casa com todas as linhas vazias e apaga dados de outras pessoas | O SQL gerado só roda se `length(trim(:titular_<coluna>)) > 0` | `test_exclusao_titular::test_parametro_vazio_nao_apaga_nada` |

## Como acrescentar um cenário

1. Descreva o incidente e o risco numa linha da matriz.
2. Escreva a defesa (expectation, alerta, monitoramento ou regra no código).
3. Escreva o teste que quebra se a defesa sumir. Se não houver risco claro, não escreva.
4. Se o incidente depende de dados no Databricks, acrescente uma versão ao gerador
   (`data/gerar_dados_exemplo.py`) e inclua-a numa das duas rodadas da integração
   (`scripts/integracao.py`, `.github/workflows/integracao.yml`,
   `tests/projeto/integracao/esperado.py` e `tests/projeto/integracao/test_carga.py`). Prefira um teste de unidade quando o risco não
   depender do Databricks.
