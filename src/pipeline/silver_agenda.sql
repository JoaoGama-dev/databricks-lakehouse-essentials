-- Preparação específica da fonte "agenda", lida por silver.py antes da limpeza padrão.
--
-- A planilha não traz a data em cada linha: ela aparece numa linha separadora
-- ("AGENDA DIA 04/08/2025;;;;;") e vale para as linhas de baixo. Como o Spark não
-- garante a ordem das linhas de um CSV, a bronze guarda cada arquivo inteiro numa
-- linha só (wholeText). Aqui o texto é quebrado em linhas, com a posição de cada
-- uma, e a data do separador é levada para as entrevistas seguintes.
--
-- Nada é limpo aqui: TRIM, de-para do status, datas e regras de qualidade vêm do
-- config/fontes.yml e são aplicados em silver.py.
CREATE TEMPORARY VIEW preparada_agenda
COMMENT 'Agenda de entrevistas em uma linha por entrevista, com a data do separador repetida em cada linha.'
AS SELECT
  data_entrevista,
  horario,
  nome_candidato,
  vaga,
  telefone,
  status,
  _linha,
  _fonte,
  _arquivo_origem,
  _ingerido_em
FROM (
  SELECT
    last(data_separador, true) OVER (
      PARTITION BY _arquivo_origem
      ORDER BY _linha
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS data_entrevista,
    try_element_at(campos, 1) AS horario,
    try_element_at(campos, 2) AS nome_candidato,
    try_element_at(campos, 3) AS vaga,
    try_element_at(campos, 4) AS telefone,
    try_element_at(campos, 5) AS status,
    data_separador IS NOT NULL AS separador,
    _linha,
    _fonte,
    _arquivo_origem,
    _ingerido_em
  FROM (
    SELECT
      posicao + 1 AS _linha,
      split(linha, ';') AS campos,
      -- O cabeçalho ("AGENDA DIA 04/08/2025;NOME;...") também é tratado como separador.
      nullif(regexp_extract(linha, '(?i)^ *AGENDA DIA +([0-9]{2}/[0-9]{2}/[0-9]{4})', 1), '') AS data_separador,
      _fonte,
      _arquivo_origem,
      _ingerido_em
    FROM (
      SELECT
        -- O Excel grava o arquivo com BOM (U+FEFF, bytes EF BB BF) no início; sem
        -- removê-lo, o cabeçalho não começaria com "AGENDA DIA" e viraria uma entrevista.
        trim(LEADING decode(unhex('EFBBBF'), 'UTF-8') FROM value) AS texto,
        _fonte,
        _arquivo_origem,
        _ingerido_em
      FROM bronze_agenda
    )
    LATERAL VIEW posexplode(split(texto, '\r?\n')) linhas AS posicao, linha
    -- Ignora linhas vazias (";;;;;") do fim da planilha.
    WHERE trim(regexp_replace(linha, '[;\r]', '')) <> ''
  )
)
WHERE NOT separador;
