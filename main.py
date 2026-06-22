"""
API de Verificação de Viabilidade - Cobertura V.tal/TIM
Verifica se um endereço (CEP + número) está dentro da área viável.
"""
import sqlite3
import re
import os
import uuid
import time
import hashlib
import httpx
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

DB_PATH = os.environ.get("DB_PATH", "/data/db/cobertura.db")

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


CAPI_TOKEN = "EAAOjhyjZCcF8BR7l977I98EALwlEpisbiLoCNd3N9ZCGAhZBwvIZAZCzH0wZBZBzZCdhjGdeZCH1OEl1SCAJLd4GZAJZCDpkrioaQB3Ga84tZCoo47oXC5umspuOaqZAOFysS3EqIBBw7fqJDkIDQAijJs1RkA6zn8Ib80WqZBD8kLSTNZBIrIRWf6EekSYJfpMbciuCy2e7wZDZD"
PIXEL_ID = "1747146199969241"

class CAPIEvent(BaseModel):
    event_name: str
    cep: str = ""

@app.post("/capi")
async def capi(payload: CAPIEvent, request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "")

    user_data = {
        "client_ip_address": ip,
        "client_user_agent": user_agent,
    }
    if payload.cep:
        cep_limpo = re.sub(r'\D', '', payload.cep)
        if cep_limpo:
            user_data["zp"] = hashlib.sha256(cep_limpo.encode()).hexdigest()

    event = {
        "event_name": payload.event_name,
        "event_time": int(time.time()),
        "event_id": str(uuid.uuid4()),
        "action_source": "website",
        "event_source_url": str(request.headers.get("referer", "https://viabilidade.vonixxsc.com.br")),
        "user_data": user_data,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v19.0/{PIXEL_ID}/events",
            params={"access_token": CAPI_TOKEN},
            json={"data": [event]},
            timeout=10,
        )
    return resp.json()

@app.get("/health")
def health():
    return {"status": "ok"}

# Servir a landing page estática
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
