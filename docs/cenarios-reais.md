# Cenários reais e como o projeto se protege

Esta página liga cada incidente que acontece em produção à defesa do projeto e ao teste
que a mantém de pé.

## A regra dos testes

**Todo teste protege contra um risco real:** dado errado, vazamento de dado pessoal, custo
inesperado, deploy quebrado ou falha de segurança. Se um teste não consegue dizer qual
desses riscos ele evita, ele não deve existir.

Por isso a forma e a ordem dos ADRs e do CHANGELOG não são testadas: isso é papel da
revisão do PR. O único teste de documentação confere que nenhum link relativo está
quebrado (`tests/test_documentacao.py`).

Os testes de unidade rodam no CI a cada PR (`pytest -q`). Os cenários de integração rodam
no target `ci`, só quando o workflow `integracao.yml` é disparado com
`cenarios_de_falha` (ver [`desenvolvimento.md`](desenvolvimento.md)).

## Matriz de incidentes

Os testes citados como `test_cenarios` estão em `tests/integracao/test_cenarios.py`; os
demais, em `tests/`.

| Incidente real | Risco | Como o projeto se protege | Teste que cobre |
| --- | --- | --- | --- |
| **v3**: a planilha chega só com o último mês (queda de volume) | Painel perde quase todo o histórico e ninguém percebe | `mon_volume` compara o retrato com a carga anterior; o alerta `qualidade_carga` avisa às 7h. A carga não para ([ADR 0014](adr/0014-mudanca-na-origem-e-volume.md)) | `test_cenarios::test_v3_queda_de_volume_avisa_sem_parar_a_carga` e `test_base_producao::test_volume_so_alerta_no_snapshot_com_retrato_vazio_ou_queda_acima_do_limite` |
| **v3**: a origem ganha uma coluna nova | Carga quebra, ou a coluna nova passa despercebida | Auto Loader em modo `rescue` guarda a coluna em `_rescued_data`; `mon_estrutura` mostra `coluna_nova` | `test_cenarios::test_v3_coluna_nova_na_origem_aparece_em_mon_estrutura` e `test_base_producao::test_bronze_de_arquivo_nao_falha_com_coluna_nova` |
| **v4**: arquivo errado, com entrevista de 2019 | Dado errado vai para o painel | A regra `data_plausivel` tem ação `falhar`: a carga para e nada é gravado. A tarefa `registrar_falha` grava o motivo em `mon_falhas` e o alerta `falha_carga` avisa ([ADR 0015](adr/0015-aviso-de-falha-com-motivo.md)) | `test_cenarios::test_v4_regra_falhar_para_a_carga_e_registra_o_motivo` e `test_projeto::test_regra_falhar_vira_expectation_que_para_a_carga` |
| **v4**: o motivo da falha cita o registro | Nome ou telefone de uma pessoa vaza por e-mail | `motivo_seguro` guarda só o nome da regra; nunca o registro | `test_cenarios::test_v4_motivo_nao_tem_dado_pessoal` e `test_base_producao::test_motivo_de_regra_falhar_traz_so_os_nomes_das_regras` |
| **v4**: depois da falha, a silver muda | Dado parcial no painel | Nada é gravado na carga que falha; a silver fica com a última carga boa | `test_cenarios::test_v4_silver_continua_com_a_ultima_carga_boa` |
| **Reenvio** (v5): o mesmo arquivo volta com outro nome | Versão falsa no histórico SCD2 | Empate na data de referência fica com o último ingerido; como o conteúdo é o mesmo, o histórico não ganha versão nova | `test_cenarios::test_reenvio_vira_o_retrato_sem_aviso` e `test_cenarios::test_silver_e_historico_continuam_os_da_v2` |
| **Fora de ordem** (v6): a planilha antiga chega depois | O painel "volta no tempo" | `data_referencia` (agenda: `max(dt_entrevista)`) escolhe o retrato pela data, não pela ingestão; `mon_estrutura` avisa `arquivo_ignorado` ([ADR 0016](adr/0016-data-de-referencia-do-snapshot.md)) | `test_cenarios::test_arquivo_atrasado_nao_vira_o_retrato_e_avisa` e `test_projeto::test_agenda_escolhe_o_retrato_pela_maior_data_de_entrevista` |
| **Só cabeçalho** (v7): arquivo sem nenhuma entrevista | Retrato vazio apaga o painel | Arquivo sem linhas não entra na disputa pelo retrato; `mon_estrutura` avisa `arquivo_ignorado` | `test_cenarios::test_arquivo_so_com_cabecalho_nao_vira_o_retrato_e_avisa` e `test_projeto::test_so_cabecalho_nao_tem_entrevista` |
| **cp1252** (v8): planilha salva fora do UTF-8 | Acentos trocados sem ninguém perceber (nomes errados) | `mon_estrutura` avisa `codificacao_invalida` quando o texto do retrato não é UTF-8 válido (`is_valid_utf8`); a carga não para. Orientação: salvar em UTF-8 | `test_cenarios::test_arquivo_fora_do_utf8_avisa_sem_parar_a_carga` e `test_base_producao::test_codificacao_invalida_olha_so_o_arquivo_do_retrato_da_fonte_texto` |
| **Full refresh** acidental | Histórico SCD2 apagado e landing reingerida (custo) | `pipelines.reset.allowed = false` na bronze de arquivo e no histórico: o Databricks recusa o full refresh do grafo inteiro sem apagar nada ([ADR 0017](adr/0017-retencao-e-exclusao-de-titular.md)) | `test_cenarios::test_full_refresh_preserva_a_bronze`, `test_cenarios::test_full_refresh_recusado_nao_apaga_a_silver_nem_a_gold` e `test_projeto::test_bronze_da_landing_e_historico_nao_sao_esvaziados_por_full_refresh` |
| **Nome de arquivo com dado pessoal** | Os avisos mostram o nome do arquivo e o expõem | Avisos de arquivo mostram só o nome, sem a pasta; o nome nunca pode ter dado pessoal ([`docs/padroes/lgpd.md`](padroes/lgpd.md)) | `test_base_producao::test_avisos_de_arquivo_mostram_so_o_nome_do_arquivo` |
| **Chave nula** | O AUTO CDC recebe chave inválida | A regra `nao_nulo` da chave é gerada sozinha, com `drop` | `test_projeto::test_chave_sem_regra_ganha_nao_nulo_com_drop_sozinha` |
| **Telefone sem máscara** | Dado pessoal completo na silver | `mascarar: telefone` deixa só DDD e 4 últimos dígitos | `test_projeto::test_telefone_e_mascarado` |
| **Ingestão ociosa** | Custo de tarefa sem fonte | `condition_task` pula a ingestão de banco e API quando não há fonte do tipo ([ADR 0004](adr/0004-ingestao-so-com-fonte.md)) | `test_monitoramento::test_ingestao_so_roda_quando_a_condicao_e_verdadeira` |
| **Comando em produção, de máquina local** | Mudança manual e sem rastro em prod | `.claude/settings.json` nega `-t prod` e os hooks bloqueiam o comando; produção só pelo `deploy.yml` ([ADR 0012](adr/0012-guardrails-do-claude-code.md)) | `test_hooks::test_comandos_perigosos_sao_bloqueados` e `test_claude_config::test_negacoes_essenciais_existem` |
| **Dado pessoal no perfil do arquivo** | O modelo vê nome ou telefone reais | `scripts/perfilar_dados.py` mostra só estrutura e formato | `test_perfilar_dados::test_perfil_nao_expoe_nomes_nem_telefones` |
| **Exclusão de titular com parâmetro vazio** | Um campo em branco casa com todas as linhas vazias e apaga dados de outras pessoas | O SQL gerado só roda se `length(trim(:titular_<coluna>)) > 0` | `test_exclusao_titular::test_parametro_vazio_nao_apaga_nada` |

## Como acrescentar um cenário

1. Descreva o incidente e o risco numa linha da matriz.
2. Escreva a defesa (expectation, alerta, monitoramento ou regra no código).
3. Escreva o teste que quebra se a defesa sumir. Se não houver risco claro, não escreva.
4. Se o incidente depende de dados no Databricks, acrescente uma versão ao gerador
   (`data/gerar_dados_exemplo.py`) e um cenário em `tests/integracao/test_cenarios.py`.
