# API de Viabilidade - Bottura Telecom

## O que tem aqui
- `main.py` - API FastAPI que verifica viabilidade por CEP + número (e opcionalmente rua)
- `cobertura.db` - banco SQLite com os endereços viáveis. **Não vive no repositório**:
  é um volume no host, em `/data/viabilidade/cobertura.db` (montado em `/data/db`).
  Em 16/11/2026 tem 6.615.756 endereços — SP 2.170.054 (V.tal + IHS), PR 1.919.416,
  RS 1.820.015, SC 706.271.
- `static/index.html` - landing page de captura que consome a API
- `Dockerfile` - pronto para build no Coolify

## Como fazer deploy no Coolify

1. Suba esta pasta inteira pra um repositório Git (GitHub/GitLab) OU
   use o "Deploy via Dockerfile" do Coolify apontando pra esta pasta.
2. No Coolify: New Resource > Application > escolha o Dockerfile build pack.
3. Porta interna: 8000
4. Configure o domínio (ex: viabilidade.vonixxsc.com.br) com SSL automático do Coolify.
5. Depois do deploy, edite `static/index.html` e troque:
   const API_URL = "http://localhost:8000";
   por:
   const API_URL = "https://viabilidade.vonixxsc.com.br";
   (ou deixe vazio "" se a página e a API estiverem no MESMO domínio)
6. Troque também o WHATSAPP_NUMERO pro número comercial real.

## Endpoints
- GET /verificar?cep=83601030&numero=2958&logradouro=Rua%20XV%20de%20Novembro
- GET /health

## Atualizando a base no futuro

**Redeploy NÃO troca a base.** O `cobertura.db` é um bind mount
(`/data/viabilidade` no host → `/data/db` no container), então ele sobrevive a
qualquer deploy. Atualizar é substituir o arquivo:

```bash
# 1. backup do atual
ssh root@2.25.180.112 "cd /data/viabilidade && cp -a cobertura.db cobertura.db.bak-$(date +%Y%m%d-%H%M%S)"
# 2. enviar o novo (comprimido; ~285 MB contra 1,2 GB)
scp cobertura.db.gz root@2.25.180.112:/data/viabilidade/
# 3. descompactar por cima e conferir
ssh root@2.25.180.112 "cd /data/viabilidade && gunzip -f cobertura.db.gz && \
  python3 -c \"import sqlite3;c=sqlite3.connect('cobertura.db');\
print(c.execute('pragma integrity_check').fetchone()[0], c.execute('select count(*) from enderecos').fetchone()[0])\""
```

Não precisa reiniciar o container: `get_conn()` abre uma conexão por requisição,
então a próxima consulta já lê o arquivo novo.

### Gerando o cobertura.db a partir das bases da TIM

Três armadilhas que fazem a busca falhar em silêncio:

1. **CEP precisa de `zfill(8)`.** A busca é igualdade exata em TEXT e 1,78 M dos
   endereços começam com zero (todo o estado de SP). Sem isso, SP entra no banco
   e mesmo assim nenhuma consulta encontra nada.
2. **`numero` é igualdade exata em TEXT**, comparado com o que a pessoa digita —
   só dígitos, sem zero à esquerda.
3. **`logradouro_norm` tem que usar a `normalize_logradouro` do `main.py` literal**,
   inclusive o fato de ela descartar acentos em vez de converter (`JOSÉ` → `JOS`).

Entram só os endereços disponíveis: descartar `RESTRICAO_FTTH=Sim`,
`BLOQ_CAPACITY=S` e `VIABILIDADE != 1`. Marcar bloqueado como viável traz de
volta o lead sem cobertura que esta página existe para evitar.
