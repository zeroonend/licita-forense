-- Schema para fase 2: base local Receita Federal
-- Alimentado por dump público da RFB (projeto minha-receita ou similar)

CREATE TABLE IF NOT EXISTS empresas (
    cnpj VARCHAR(14) PRIMARY KEY,
    razao_social TEXT,
    nome_fantasia TEXT,
    situacao_cadastral VARCHAR(10),
    data_situacao DATE,
    natureza_juridica VARCHAR(10),
    cnae_principal VARCHAR(10),
    capital_social NUMERIC(15,2),
    porte VARCHAR(5),
    data_inicio_atividade DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS socios (
    id SERIAL PRIMARY KEY,
    cnpj_empresa VARCHAR(14) REFERENCES empresas(cnpj),
    nome_socio TEXT,
    cpf_cnpj_socio VARCHAR(14),
    qualificacao VARCHAR(5),
    data_entrada DATE,
    pais_socio VARCHAR(5)
);

-- Relação com `empresas`:
--   estabelecimentos.cnpj_basico = primeiros 8 dígitos de empresas.cnpj (raiz do CNPJ)
--   JOIN: WHERE empresas.cnpj LIKE estabelecimentos.cnpj_basico || '%'
--   Não há FK direta porque cnpj_basico é um prefixo, não a PK de empresas.
CREATE TABLE IF NOT EXISTS estabelecimentos (
    cnpj VARCHAR(14) PRIMARY KEY,
    cnpj_basico VARCHAR(8),
    logradouro TEXT,
    numero VARCHAR(20),
    municipio VARCHAR(10),
    uf VARCHAR(2),
    cep VARCHAR(8),
    telefone_1 VARCHAR(15),
    email TEXT
);

-- Índices para travessia reversa de sócios
CREATE INDEX IF NOT EXISTS idx_socios_nome ON socios(nome_socio);
CREATE INDEX IF NOT EXISTS idx_socios_cpf ON socios(cpf_cnpj_socio);
CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios(cnpj_empresa);
CREATE INDEX IF NOT EXISTS idx_estab_basico ON estabelecimentos(cnpj_basico);
