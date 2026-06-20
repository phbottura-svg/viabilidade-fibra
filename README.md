# API de Viabilidade - Bottura Telecom

## O que tem aqui
- `main.py` - API FastAPI que verifica viabilidade por CEP + número (e opcionalmente rua)
- `cobertura.db` - banco SQLite com os 1.919.226 endereços da base V.tal/TIM Paraná
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
Quando a V.tal mandar uma base nova, é só rodar o script de importação
de novo (gera um novo cobertura.db) e fazer redeploy no Coolify.
