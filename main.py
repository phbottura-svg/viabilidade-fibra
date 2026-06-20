"""
API de Verificação de Viabilidade - Cobertura V.tal/TIM
Verifica se um endereço (CEP + número) está dentro da área viável.
"""
import sqlite3
import re
import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

DB_PATH = os.path.join(os.path.dirname(__file__), "cobertura.db")

app = FastAPI(title="API Viabilidade Bottura Telecom")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def normalize_cep(cep: str) -> str:
    return re.sub(r'\D', '', cep or '')

def normalize_logradouro(s: str) -> str:
    if not s:
        return ""
    s = s.upper().strip()
    s = re.sub(r'[^A-Z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'^(RUA|AV|AVENIDA|TRAVESSA|ALAMEDA|ESTRADA|RODOVIA|R |AL )\s*', '', s)
    return s.strip()

@app.get("/verificar")
def verificar(
    cep: str = Query(..., description="CEP do endereço (com ou sem hífen)"),
    numero: str = Query("", description="Número do endereço"),
    logradouro: str = Query("", description="Nome da rua (opcional, melhora a precisão)")
):
    cep_clean = normalize_cep(cep)
    if len(cep_clean) != 8:
        return {"status": "erro", "mensagem": "CEP inválido. Use um CEP com 8 dígitos."}

    conn = get_conn()
    cur = conn.cursor()

    # 1) Tenta match exato: CEP + numero
    cur.execute(
        "SELECT * FROM enderecos WHERE cep = ? AND numero = ? AND viabilidade = 1 LIMIT 5",
        (cep_clean, str(numero).strip())
    )
    rows = cur.fetchall()

    match_type = "exato_cep_numero"

    # 2) Se não achou e veio logradouro, tenta CEP + logradouro normalizado (ignora numero exato,
    #    pega o numero mais próximo na mesma rua/CEP)
    if not rows and logradouro:
        logr_norm = normalize_logradouro(logradouro)
        cur.execute(
            "SELECT * FROM enderecos WHERE cep = ? AND logradouro_norm = ? AND viabilidade = 1",
            (cep_clean, logr_norm)
        )
        candidatos = cur.fetchall()
        if candidatos:
            rows = candidatos
            match_type = "aproximado_rua"

    # 3) Se ainda não achou, tenta só pelo CEP (mostra se a região tem cobertura, mas sem garantir o número exato)
    regiao_tem_cobertura = False
    if not rows:
        cur.execute(
            "SELECT COUNT(*) as n, MIN(municipio) as municipio, MIN(bairro) as bairro FROM enderecos WHERE cep = ? AND viabilidade = 1",
            (cep_clean,)
        )
        r = cur.fetchone()
        if r and r["n"] > 0:
            regiao_tem_cobertura = True
            municipio = r["municipio"]
            bairro = r["bairro"]

    conn.close()

    if rows:
        r = rows[0]
        return {
            "status": "viavel",
            "match_type": match_type,
            "endereco": {
                "logradouro": r["logradouro"],
                "numero": r["numero"],
                "bairro": r["bairro"],
                "municipio": r["municipio"],
                "uf": r["uf"],
                "cep": r["cep"],
                "tipo_lote": r["tipo_lote"]
            },
            "mensagem": "Endereço com viabilidade técnica confirmada! 🎉"
        }
    elif regiao_tem_cobertura:
        return {
            "status": "regiao_parcial",
            "endereco": {"cep": cep_clean, "municipio": municipio, "bairro": bairro},
            "mensagem": "A região do seu CEP já tem cobertura, mas não conseguimos confirmar o número exato. Um consultor vai validar manualmente."
        }
    else:
        return {
            "status": "nao_viavel",
            "mensagem": "Ainda não chegamos nessa região, mas podemos te avisar assim que a rede expandir."
        }


@app.get("/health")
def health():
    return {"status": "ok"}

# Servir a landing page estática
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
