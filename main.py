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

    # 2) Número não cadastrado: a rua tem fibra, mas aquela fachada não está
    #    na base. Devolve o logradouro para a tela mostrá-lo igual ao caso
    #    viável — é a informação com que o consultor cadastra a fachada.
    #
    #    Só o número EXATO confirma viabilidade. Antes, quando o visitante
    #    digitava a rua, qualquer endereço dela servia de resposta: quem
    #    procurava o 1869 recebia "cobertura confirmada" exibindo o 866. Isso
    #    é falso positivo — gera lead que o técnico não consegue instalar.
    #
    #    A rua digitada ainda é usada, mas só para escolher QUAL rua mostrar
    #    nos poucos CEPs com mais de uma (1,6% da base). Sem ela, fica a rua
    #    com mais endereços cadastrados no CEP.
    regiao_tem_cobertura = False
    cep_corrigido = None
    if not rows:
        parametros = [cep_clean]
        filtro_rua = ""
        if logradouro:
            logr_norm = normalize_logradouro(logradouro)
            cur.execute(
                "SELECT 1 FROM enderecos WHERE cep = ? AND logradouro_norm = ? "
                "AND viabilidade = 1 LIMIT 1",
                (cep_clean, logr_norm)
            )
            if cur.fetchone():
                filtro_rua = "AND logradouro_norm = ? "
                parametros.append(logr_norm)

        cur.execute(
            "SELECT COUNT(*) as n, logradouro, logradouro_norm, bairro, municipio, uf "
            "FROM enderecos WHERE cep = ? " + filtro_rua +
            "AND viabilidade = 1 GROUP BY logradouro ORDER BY n DESC LIMIT 1",
            parametros
        )
        r = cur.fetchone()
        if r and r["n"] > 0:
            regiao_tem_cobertura = True
            logradouro_cep = r["logradouro"]
            municipio = r["municipio"]
            bairro = r["bairro"]
            uf_cep = r["uf"]

            # 3) Ruas longas são fatiadas em vários CEPs por faixa de número, e
            #    o visitante costuma digitar o CEP de outra faixa. Ex.: Rua das
            #    Carmelitas em Curitiba tem 81610070 (0-975), 81650060
            #    (1036-3189) e 81730050 (3233-5410) — quem mora no 1869 e
            #    digita o primeiro tem o endereço atendido, só sob outro CEP.
            #    Procura o mesmo número na mesma rua e cidade, em outro CEP.
            #
            #    Só aceita quando UM único CEP responde: 99,79% das
            #    combinações (cidade, rua, número) existem num CEP só; no
            #    resto há ruas homônimas, e aí é mais honesto cair no
            #    "cadastrar fachada" do que apontar o CEP errado.
            cur.execute(
                "SELECT DISTINCT cep FROM enderecos "
                "WHERE municipio = ? AND logradouro_norm = ? AND numero = ? "
                "AND viabilidade = 1 LIMIT 2",
                (municipio, r["logradouro_norm"], str(numero).strip())
            )
            outros = cur.fetchall()
            if len(outros) == 1:
                cur.execute(
                    "SELECT * FROM enderecos WHERE cep = ? AND numero = ? "
                    "AND viabilidade = 1 LIMIT 1",
                    (outros[0]["cep"], str(numero).strip())
                )
                achado = cur.fetchone()
                if achado:
                    rows = [achado]
                    cep_corrigido = outros[0]["cep"]

    conn.close()

    if rows:
        r = rows[0]
        if cep_corrigido:
            cep_fmt = f"{cep_corrigido[:5]}-{cep_corrigido[5:]}"
            mensagem = (
                "Endereço com viabilidade técnica confirmada! 🎉 "
                f"Atenção: o CEP deste número é {cep_fmt}."
            )
        else:
            mensagem = "Endereço com viabilidade técnica confirmada! 🎉"
        return {
            "status": "viavel",
            # Viabilidade só é confirmada pelo número exato. "corrigido_cep"
            # é o mesmo número achado sob outro CEP da mesma rua.
            "match_type": "corrigido_cep" if cep_corrigido else "exato_cep_numero",
            "endereco": {
                "logradouro": r["logradouro"],
                "numero": r["numero"],
                "bairro": r["bairro"],
                "municipio": r["municipio"],
                "uf": r["uf"],
                "cep": r["cep"],
                "tipo_lote": r["tipo_lote"]
            },
            "mensagem": mensagem
        }
    elif regiao_tem_cobertura:
        return {
            "status": "regiao_parcial",
            "endereco": {
                "cep": cep_clean,
                "logradouro": logradouro_cep,
                "numero": str(numero).strip(),
                "bairro": bairro,
                "municipio": municipio,
                "uf": uf_cep
            },
            "mensagem": "Rua possui fibra — necessário cadastrar fachada."
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
