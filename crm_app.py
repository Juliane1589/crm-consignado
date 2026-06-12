"""
CRM Consignado - Juliane
Railway + PostgreSQL + Flask + Gunicorn
+ Radar de Reajustes (monitor em background thread)
"""

import json
import os
import time
import threading
import logging
import psycopg2
import psycopg2.extras
import pandas as pd
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from flask import Flask, request, Response, jsonify

try:
    import requests as req_lib
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

app = Flask(__name__)
log = logging.getLogger(__name__)

PORT = int(os.environ.get('PORT', 8765))

# ── WhatsApp ──────────────────────────────────────────────────────────────────
WHATSAPP_VERIFY_TOKEN = os.environ.get('WA_VERIFY_TOKEN', 'Meucrm26')
WHATSAPP_TOKEN        = os.environ.get('WA_TOKEN', 'EAAVXA6vwBM4BRiTlfKFBBYbUPcNSomsaLZALG8PO3RI7TxshlJSCZCTmlENGUSWfopuPEL0zV5uj3tLMQdnw23r8b036t3k1iayPOv2Hs3NwWNt1a8TZC1rpeVIc8TvrpFqegAgZBD61gUsAVO1ZCe9Q6NMsEbkatzKTYdp4IyALoXTfi921ZA5TFMucIohgZDZD')
WHATSAPP_PHONE_ID     = os.environ.get('WA_PHONE_ID', '1166793639847817')
DATABASE_URL          = os.environ.get('DATABASE_URL', '')

# ── BANCO DE DADOS ────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def normalizar_numero(numero):
    n = ''.join(filter(str.isdigit, numero))
    if n.startswith('0'): n = n[1:]
    if not n.startswith('55'): n = '55' + n
    if len(n) == 12: n = n[:4] + '9' + n[4:]
    return n

def init_db():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            dados JSONB NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mensagens (
            numero TEXT PRIMARY KEY,
            dados JSONB NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS disparos (
            id SERIAL PRIMARY KEY,
            data_hora TIMESTAMP DEFAULT NOW(),
            template TEXT,
            total INTEGER,
            enviados INTEGER,
            erros INTEGER,
            log JSONB
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reajustes (
            id SERIAL PRIMARY KEY,
            data_publicacao DATE,
            data_detectado TIMESTAMP DEFAULT NOW(),
            municipio TEXT,
            estado TEXT,
            titulo TEXT,
            trecho TEXT,
            url TEXT,
            fonte TEXT DEFAULT 'Querido Diário',
            visualizado BOOLEAN DEFAULT FALSE,
            UNIQUE(url, municipio)
        )
    """)
    conn.commit(); cur.close(); conn.close()
    print("✅ Banco inicializado")

def carregar_dados():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT dados FROM clientes ORDER BY dados->>'nome'")
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {"clientes": [r[0] for r in rows]}
    except Exception as e:
        print(f"Erro carregar_dados: {e}")
        return {"clientes": []}

def salvar_cliente(c):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (id, dados) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET dados = EXCLUDED.dados
        """, (str(c['id']), json.dumps(c, ensure_ascii=False)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"Erro salvar_cliente: {e}")

def salvar_todos_clientes(lista):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM clientes")
        for c in lista:
            cur.execute("""
                INSERT INTO clientes (id, dados) VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET dados = EXCLUDED.dados
            """, (str(c['id']), json.dumps(c, ensure_ascii=False)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"Erro salvar_todos: {e}")

def excluir_cliente_db(id_cliente):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM clientes WHERE id = %s", (str(id_cliente),))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"Erro excluir_cliente: {e}")

def carregar_mensagens():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT numero, dados FROM mensagens")
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {"conversas": {r[0]: r[1] for r in rows}}
    except Exception as e:
        print(f"Erro carregar_mensagens: {e}")
        return {"conversas": {}}

def salvar_conversa(numero, dados):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO mensagens (numero, dados) VALUES (%s, %s)
            ON CONFLICT (numero) DO UPDATE SET dados = EXCLUDED.dados
        """, (numero, json.dumps(dados, ensure_ascii=False)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"Erro salvar_conversa: {e}")

def salvar_disparo(template, total, enviados, erros, log_data):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO disparos (template, total, enviados, erros, log)
            VALUES (%s, %s, %s, %s, %s)
        """, (template, total, enviados, erros, json.dumps(log_data, ensure_ascii=False)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"Erro salvar_disparo: {e}")

def carregar_historico_disparos():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, data_hora, template, total, enviados, erros, log FROM disparos ORDER BY data_hora DESC LIMIT 50")
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [{"id":r[0],"data_hora":r[1].strftime('%d/%m/%Y %H:%M'),"template":r[2],"total":r[3],"enviados":r[4],"erros":r[5],"log":r[6]} for r in rows]
    except Exception as e:
        print(f"Erro carregar_historico: {e}")
        return []

# ── REAJUSTES ─────────────────────────────────────────────────────────────────
def carregar_reajustes():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT id, data_publicacao, data_detectado, municipio, estado,
                   titulo, trecho, url, fonte, visualizado
            FROM reajustes
            ORDER BY data_publicacao DESC NULLS LAST, data_detectado DESC
            LIMIT 200
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [{
            'id': r[0],
            'data_publicacao': r[1].strftime('%d/%m/%Y') if r[1] else '',
            'data_detectado':  r[2].strftime('%d/%m/%Y %H:%M') if r[2] else '',
            'municipio': r[3] or '',
            'estado':    r[4] or '',
            'titulo':    r[5] or '',
            'trecho':    r[6] or '',
            'url':       r[7] or '',
            'fonte':     r[8] or '',
            'visualizado': r[9],
        } for r in rows]
    except Exception as e:
        print(f"Erro carregar_reajustes: {e}")
        return []

def contar_reajustes_novos():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reajustes WHERE visualizado = FALSE")
        count = cur.fetchone()[0]
        cur.close(); conn.close()
        return count
    except:
        return 0

def salvar_reajuste(data_pub, municipio, estado, titulo, trecho, url):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO reajustes (data_publicacao, municipio, estado, titulo, trecho, url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (url, municipio) DO NOTHING
        """, (data_pub, municipio, estado, titulo, trecho, url))
        inserted = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return inserted > 0
    except Exception as e:
        print(f"Erro salvar_reajuste: {e}")
        return False

def marcar_reajuste_visto(id_reajuste):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE reajustes SET visualizado = TRUE WHERE id = %s", (id_reajuste,))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"Erro marcar_visto: {e}")

# ── MONITOR DE REAJUSTES (background thread) ──────────────────────────────────
PALAVRAS_CHAVE = [
    "concede reajuste servidor",
    "revisão geral anual",
    "reajuste salarial servidor público",
    "aumento salarial servidor público",
    "altera tabela de vencimentos",
    "reestrutura plano de cargos",
    "reajuste vencimento servidor",
]

# Headers que simulam navegador real para evitar bloqueio 403
HEADERS_NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*; q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

def buscar_querido_diario(termo, dias_atras=8):
    if not REQUESTS_OK:
        return None
    data_inicio = (date.today() - timedelta(days=dias_atras)).strftime('%Y-%m-%d')
    # Tenta o endpoint correto com headers de navegador
    for base_url in [
        "https://api.queridodiario.ok.org.br/gazettes",
        "https://queridodiario.ok.org.br/api/gazettes",
    ]:
        params = {
            "querystring": termo,
            "published_since": data_inicio,
            "size": 20,
            "sort_by": "descending_date",
            "is_municipality": "true",
        }
        try:
            import requests as rlib
            sess = rlib.Session()
            sess.headers.update(HEADERS_NAVEGADOR)
            # Faz uma requisição inicial para pegar cookies
            sess.get("https://queridodiario.ok.org.br/", timeout=10)
            resp = sess.get(base_url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            print(f"[RADAR] {base_url} retornou {resp.status_code} para '{termo}'")
        except Exception as e:
            print(f"[RADAR] Erro '{base_url}': {e}")
        time.sleep(2)
    return None

def buscar_in_gov(termo, dias_atras=8):
    """Busca no Portal da Imprensa Nacional (DOU) como fonte alternativa."""
    if not REQUESTS_OK:
        return []
    import requests as rlib
    import urllib.parse
    from datetime import date, timedelta
    import re

    data_inicio = (date.today() - timedelta(days=dias_atras)).strftime('%d/%m/%Y')
    data_fim    = date.today().strftime('%d/%m/%Y')

    url = "https://www.in.gov.br/consulta/-/buscar-resultados"
    params = {
        'q': termo,
        'exactDate': 'personalizado',
        'publicacaoInicio': data_inicio,
        'publicacaoFim': data_fim,
        'sortType': '0',
        'delta': '20',
        'pageNumber': '1',
    }
    try:
        sess = rlib.Session()
        sess.headers.update(HEADERS_NAVEGADOR)
        resp = sess.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"[RADAR] IN.gov retornou {resp.status_code} para '{termo}'")
            return []

        # Extrai resultados do HTML
        html = resp.text
        resultados = []

        # Padrão para encontrar títulos e links no HTML do DOU
        links = re.findall(r'href="(https://www\.in\.gov\.br/web/dou/-/[^"]+)"[^>]*>([^<]+)<', html)
        for link, titulo in links[:10]:
            # Tenta extrair município do título
            municipio = 'Município não identificado'
            estado = '??'
            # Busca padrão "município de NOME" ou "prefeitura de NOME"
            m = re.search(r'(?:município|prefeitura|câmara)\s+(?:de|do|da|dos|das)\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ][a-záéíóúâêîôûãõç\s]+?)(?:\s*[-/,]|\s+estado|\s+–|$)', titulo, re.IGNORECASE)
            if m:
                municipio = m.group(1).strip()

            resultados.append({
                'municipio': municipio,
                'estado': estado,
                'data_pub': date.today(),
                'titulo': titulo.strip(),
                'trecho': titulo.strip(),
                'url': link,
                'fonte': 'DOU',
            })
        return resultados
    except Exception as e:
        print(f"[RADAR] Erro IN.gov '{termo}': {e}")
        return []

def processar_gazette(gazette):
    municipio = gazette.get('territory_name', 'Desconhecido')
    estado    = gazette.get('state_code', '??')
    data_str  = gazette.get('date', '')
    url       = gazette.get('url', '')
    excerpts  = gazette.get('excerpts', [])
    try:
        data_pub = datetime.strptime(data_str, '%Y-%m-%d').date()
    except:
        data_pub = date.today()
    titulo = f"Diário Oficial — {municipio}/{estado} — {data_str}"
    trecho = excerpts[0] if excerpts else ''
    trecho = trecho.replace('<em>', '').replace('</em>', '').replace('<br>', ' ')
    if len(trecho) > 800:
        trecho = trecho[:800] + '...'
    return {'municipio': municipio, 'estado': estado, 'data_pub': data_pub,
            'titulo': titulo, 'trecho': trecho, 'url': url, 'fonte': 'Querido Diário'}

def executar_busca_radar(dias_atras=8):
    print(f"[RADAR] 🔍 Iniciando busca ({date.today()})...")
    novos = 0
    urls_vistas = set()
    qd_funcionou = False

    for termo in PALAVRAS_CHAVE:
        # Tenta Querido Diário primeiro
        resultado = buscar_querido_diario(termo, dias_atras=dias_atras)
        if resultado:
            qd_funcionou = True
            gazettes = resultado.get('gazettes', [])
            print(f"[RADAR] QD '{termo}' → {len(gazettes)} publicações")
            for gazette in gazettes:
                url = gazette.get('url', '')
                if url in urls_vistas:
                    continue
                urls_vistas.add(url)
                dados = processar_gazette(gazette)
                inserido = salvar_reajuste(
                    data_pub=dados['data_pub'], municipio=dados['municipio'],
                    estado=dados['estado'],    titulo=dados['titulo'],
                    trecho=dados['trecho'],    url=dados['url'],
                )
                if inserido:
                    novos += 1
                    print(f"[RADAR] ✅ NOVO (QD): {dados['municipio']}/{dados['estado']}")
        else:
            # Fallback: Imprensa Nacional (DOU)
            print(f"[RADAR] QD falhou, tentando DOU para '{termo}'...")
            resultados_dou = buscar_in_gov(termo, dias_atras=dias_atras)
            print(f"[RADAR] DOU '{termo}' → {len(resultados_dou)} publicações")
            for dados in resultados_dou:
                url = dados['url']
                if url in urls_vistas:
                    continue
                urls_vistas.add(url)
                inserido = salvar_reajuste(
                    data_pub=dados['data_pub'], municipio=dados['municipio'],
                    estado=dados['estado'],    titulo=dados['titulo'],
                    trecho=dados['trecho'],    url=dados['url'],
                )
                if inserido:
                    novos += 1
                    print(f"[RADAR] ✅ NOVO (DOU): {dados['municipio']}")
        time.sleep(3)

    print(f"[RADAR] ✅ Busca concluída: {novos} reajustes novos | QD ok={qd_funcionou}")
    return novos

def loop_monitor():
    """Roda em background thread — busca todo dia às 7h."""
    time.sleep(15)  # espera o app subir
    print("[RADAR] 🚀 Monitor de reajustes iniciado")
    print("[RADAR] 📅 Busca inicial (últimos 30 dias)...")
    executar_busca_radar(dias_atras=30)

    while True:
        agora = datetime.now()
        proximo = agora.replace(hour=7, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        espera = (proximo - agora).total_seconds()
        horas  = int(espera // 3600)
        mins   = int((espera % 3600) // 60)
        print(f"[RADAR] 💤 Próxima busca em {horas}h {mins}min")
        time.sleep(espera)
        executar_busca_radar(dias_atras=8)

# ── WHATSAPP ──────────────────────────────────────────────────────────────────
def enviar_whatsapp(telefone, mensagem):
    numero = normalizar_numero(telefone)
    payload = json.dumps({
        "messaging_product": "whatsapp", "to": numero,
        "type": "text", "text": {"body": mensagem}
    }).encode('utf-8')
    req = urllib.request.Request(
        f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages",
        data=payload,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp: return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        erro = e.read().decode('utf-8'); print(f"❌ Erro WhatsApp: {erro}"); return {"erro": erro}
    except Exception as e: return {"erro": str(e)}

def enviar_template(telefone, template_name, nome_cliente):
    numero = normalizar_numero(telefone)
    payload = json.dumps({
        "messaging_product": "whatsapp", "to": numero, "type": "template",
        "template": {
            "name": template_name, "language": {"code": "pt_BR"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": nome_cliente}]}]
        }
    }).encode('utf-8')
    req = urllib.request.Request(
        f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages",
        data=payload,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp: return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        erro = e.read().decode('utf-8'); print(f"❌ Erro template {numero}: {erro}"); return {"erro": erro}
    except Exception as e: return {"erro": str(e)}

disparo_status = {"ativo": False, "total": 0, "enviados": 0, "erros": 0, "log": [], "cancelar": False}

# ── INIT ──────────────────────────────────────────────────────────────────────
if DATABASE_URL:
    init_db()
    dados_globais     = carregar_dados()
    mensagens_globais = carregar_mensagens()
    # Inicia monitor em background
    t = threading.Thread(target=loop_monitor, daemon=True)
    t.start()
else:
    print("⚠️ DATABASE_URL não configurado!")
    dados_globais     = {"clientes": []}
    mensagens_globais = {"conversas": {}}


HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CRM Consignado</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0D0D0F;--surface:#16161A;--surface2:#1E1E24;--border:#2A2A32;--border2:#333340;
  --text:#F0EFE8;--muted:#6B6B78;--muted2:#4A4A55;
  --green:#2ECC71;--green-dim:#1A3D2A;--green-text:#5AE68A;
  --amber:#F59E0B;--amber-dim:#3D2E10;--amber-text:#FCD34D;
  --red:#EF4444;--red-dim:#3D1515;--red-text:#FCA5A5;
  --blue:#3B82F6;--blue-dim:#1A2B4A;--blue-text:#93C5FD;
  --accent:#7C5CFC;--accent2:#A78BFA;--sidebar-w:240px;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:'Instrument Sans',sans-serif;font-size:14px;overflow:hidden}
::-webkit-scrollbar{width:5px;height:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:10px}
.layout{display:flex;height:100vh}
.sidebar{width:var(--sidebar-w);background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:0;position:fixed;height:100vh;z-index:10;flex-shrink:0}
.main{margin-left:var(--sidebar-w);flex:1;overflow-y:auto;height:100vh;background:var(--bg)}
.main-inner{padding:32px 36px;max-width:1200px}
.logo-area{padding:24px 20px 20px;border-bottom:1px solid var(--border)}
.logo-name{font-family:'Syne',sans-serif;font-size:17px;font-weight:800;letter-spacing:-.3px;color:var(--text)}
.logo-tag{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted);margin-top:3px;text-transform:uppercase;letter-spacing:1px}
.nav{padding:12px 10px;flex:1;overflow-y:auto}
.nav-section{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted2);text-transform:uppercase;letter-spacing:1.5px;padding:16px 10px 6px}
.nav-btn{display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer;color:var(--muted);font-size:13px;font-weight:500;border-radius:8px;border:none;background:none;width:100%;text-align:left;font-family:'Instrument Sans',sans-serif;transition:all .15s;position:relative;margin-bottom:2px}
.nav-btn:hover{color:var(--text);background:var(--surface2)}
.nav-btn.active{color:var(--text);background:var(--surface2);font-weight:600}
.nav-btn.active::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:60%;background:var(--accent);border-radius:0 3px 3px 0}
.nav-icon{font-size:15px;width:20px;text-align:center;flex-shrink:0}
.nav-badge{margin-left:auto;background:var(--red);color:#fff;font-size:10px;font-family:'DM Mono',monospace;padding:1px 7px;border-radius:20px;font-weight:500}
.sidebar-footer{padding:16px 20px;border-top:1px solid var(--border)}
.sidebar-footer-text{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted2)}
.page{display:none}.page.active{display:block}
.page-header{margin-bottom:28px}
.page-title{font-family:'Syne',sans-serif;font-size:26px;font-weight:800;letter-spacing:-.5px;color:var(--text);line-height:1}
.page-sub{font-size:13px;color:var(--muted);margin-top:6px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px}
.metric{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;position:relative;overflow:hidden;transition:border-color .2s}
.metric:hover{border-color:var(--border2)}
.metric-label{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.metric-value{font-family:'Syne',sans-serif;font-size:32px;font-weight:800;letter-spacing:-1px;line-height:1}
.metric-value.c-green{color:var(--green-text)}.metric-value.c-amber{color:var(--amber-text)}.metric-value.c-red{color:var(--red-text)}.metric-value.c-blue{color:var(--blue-text)}
.metric-accent{position:absolute;right:16px;top:16px;font-size:22px;opacity:.25}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:16px}
.card-title{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:var(--text);margin-bottom:16px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}
.fg{display:flex;flex-direction:column;gap:5px}.fg.full{grid-column:1/-1}
label{font-family:'DM Mono',monospace;font-size:10px;font-weight:500;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}
input[type=text],input[type=date],input[type=email],select,textarea{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:9px 12px;font-size:13px;font-family:'Instrument Sans',sans-serif;color:var(--text);outline:none;transition:border-color .15s;width:100%}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
select option{background:var(--surface2)}textarea{resize:vertical;min-height:80px}
input::placeholder,textarea::placeholder{color:var(--muted2)}
.btn{display:inline-flex;align-items:center;gap:7px;padding:9px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;font-family:'Instrument Sans',sans-serif;transition:all .15s;white-space:nowrap}
.btn-primary{background:var(--accent);color:#fff}.btn-primary:hover{background:#6B4DE8}
.btn-ghost{background:none;border:1px solid var(--border);color:var(--text)}.btn-ghost:hover{border-color:var(--border2);background:var(--surface2)}
.btn-danger{background:none;border:1px solid var(--border);color:var(--red-text);font-size:12px;padding:6px 12px}.btn-danger:hover{border-color:var(--red);background:var(--red-dim)}
.btn-edit{background:none;border:1px solid var(--border);color:var(--muted);font-size:12px;padding:6px 12px}.btn-edit:hover{border-color:var(--border2);color:var(--text);background:var(--surface2)}
.btn-wpp{background:#25D366;color:#fff;font-size:12px;padding:6px 12px}.btn-wpp:hover{background:#1DB954}
.btn-sm{padding:5px 10px;font-size:11px}
.btn-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.badge{display:inline-flex;align-items:center;gap:4px;font-family:'DM Mono',monospace;font-size:10px;font-weight:500;padding:3px 9px;border-radius:20px;white-space:nowrap}
.badge-fechou{background:var(--green-dim);color:var(--green-text);border:1px solid #2ECC7130}
.badge-negoc{background:var(--surface2);color:var(--muted);border:1px solid var(--border)}
.badge-carteira{background:var(--blue-dim);color:var(--blue-text);border:1px solid #3B82F630}
.badge-atrasado{background:var(--red-dim);color:var(--red-text);border:1px solid #EF444430}
.badge-hoje{background:var(--amber-dim);color:var(--amber-text);border:1px solid #F59E0B30}
.badge-breve{background:var(--amber-dim);color:var(--amber-text);border:1px solid #F59E0B30}
.badge-ok{background:var(--surface2);color:var(--muted);border:1px solid var(--border)}
.filter-bar{display:flex;gap:10px;margin-bottom:16px;align-items:center}
.filter-bar input{flex:1}.filter-bar select{width:170px}
.results-count{font-family:'DM Mono',monospace;font-size:11px;color:var(--muted);margin-left:auto;white-space:nowrap}
.client-list{display:flex;flex-direction:column;gap:8px}
.client-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;transition:border-color .15s}
.client-card:hover{border-color:var(--border2)}
.cc-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}
.cc-name{font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:var(--text)}
.cc-badges{display:flex;gap:6px;flex-wrap:wrap}
.cc-info{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}
.cc-field{font-size:12px;color:var(--muted)}.cc-field strong{color:var(--text);font-weight:500}
.cc-obs{font-size:12px;color:var(--muted);background:var(--surface2);border:1px solid var(--border);padding:8px 12px;border-radius:6px;margin-bottom:10px;font-style:italic}
.cc-actions{display:flex;gap:8px;flex-wrap:wrap}
.retorno-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 18px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:12px;transition:border-color .15s}
.retorno-card:hover{border-color:var(--border2)}
.rc-left{flex:1;min-width:0}.rc-nome{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;margin-bottom:3px}
.rc-detail{font-size:12px;color:var(--muted)}.rc-right{display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0}
.rc-date{font-family:'DM Mono',monospace;font-size:11px;color:var(--muted)}
.dash-section-title{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}
.chat-layout{display:flex;height:calc(100vh - 64px);gap:16px}
.chat-list-col{width:320px;flex-shrink:0;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
.chat-list-header{padding:14px 16px;border-bottom:1px solid var(--border);font-family:'Syne',sans-serif;font-size:14px;font-weight:700}
.chat-list-body{flex:1;overflow-y:auto}
.chat-item{padding:12px 16px;cursor:pointer;border-bottom:1px solid var(--border);transition:background .12s;position:relative}
.chat-item:hover{background:var(--surface2)}.chat-item.active{background:var(--surface2)}.chat-item.unread{border-left:3px solid var(--accent)}
.ci-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}
.ci-name{font-weight:600;font-size:13px}.ci-time{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted)}
.ci-preview{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}
.ci-badge{background:var(--accent);color:#fff;font-size:9px;font-family:'DM Mono',monospace;padding:1px 5px;border-radius:10px;margin-left:4px}
.chat-win{flex:1;background:var(--surface);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;overflow:hidden}
.chat-win-empty{flex:1;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;color:var(--muted)}
.cw-header{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
.cw-contact-name{font-family:'Syne',sans-serif;font-size:14px;font-weight:700}
.cw-contact-num{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted)}
.cw-body{flex:1;overflow-y:auto;padding:16px 18px;display:flex;flex-direction:column;gap:8px;background:var(--bg)}
.msg-bubble{max-width:72%;padding:9px 14px;border-radius:10px;font-size:13px;line-height:1.5;word-break:break-word}
.msg-bubble.recv{background:var(--surface);border:1px solid var(--border);align-self:flex-start;border-radius:2px 10px 10px 10px}
.msg-bubble.sent{background:var(--accent);color:#fff;align-self:flex-end;border-radius:10px 2px 10px 10px}
.msg-time{font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,.5);margin-top:3px;text-align:right}
.msg-bubble.recv .msg-time{color:var(--muted)}
.cw-footer{padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px;align-items:center}
.cw-footer input{flex:1}.cw-footer .btn{flex-shrink:0}
.drop-area{border:2px dashed var(--border);border-radius:12px;padding:36px;text-align:center;cursor:pointer;transition:border-color .2s;margin-bottom:20px}
.drop-area:hover{border-color:var(--accent)}
.drop-icon{font-size:36px;margin-bottom:10px}.drop-label{font-weight:600;font-size:14px;margin-bottom:4px}.drop-hint{font-size:12px;color:var(--muted)}
.col-map-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}
.cm-item{display:flex;flex-direction:column;gap:5px}.preview-wrap{overflow-x:auto;margin-bottom:16px}
table.prev{width:100%;border-collapse:collapse;font-size:12px}
table.prev th{background:var(--surface2);padding:8px 12px;text-align:left;font-family:'DM Mono',monospace;font-size:10px;font-weight:500;color:var(--muted);border-bottom:1px solid var(--border)}
table.prev td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text)}
.toast{position:fixed;bottom:24px;right:24px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 18px;font-size:13px;display:flex;align-items:center;gap:10px;box-shadow:0 8px 32px rgba(0,0,0,.4);transform:translateY(80px);opacity:0;transition:all .3s;z-index:100}
.toast.show{transform:translateY(0);opacity:1}.toast.success{border-color:var(--green);color:var(--green-text)}.toast.error{border-color:var(--red);color:var(--red-text)}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);z-index:50;display:none;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:28px;width:500px;max-width:95vw;max-height:90vh;overflow-y:auto}
.modal-title{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;margin-bottom:20px}
.modal-footer{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
.loading{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.empty{text-align:center;padding:48px 32px;color:var(--muted)}.empty-icon{font-size:36px;margin-bottom:10px;opacity:.4}.empty-text{font-size:14px}
.pagination{display:flex;gap:6px;align-items:center;justify-content:center;padding:16px 0}
.pg-btn{background:var(--surface);border:1px solid var(--border);color:var(--text);padding:6px 12px;border-radius:6px;cursor:pointer;font-family:'DM Mono',monospace;font-size:12px}
.pg-btn:hover{border-color:var(--border2);background:var(--surface2)}.pg-btn.active{background:var(--accent);border-color:var(--accent);color:#fff}.pg-btn:disabled{opacity:.3;cursor:not-allowed}
.pg-info{font-family:'DM Mono',monospace;font-size:11px;color:var(--muted);padding:0 8px}
.tabs{display:flex;gap:4px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:4px;margin-bottom:20px;width:fit-content}
.tab-btn{padding:6px 16px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;border:none;background:none;color:var(--muted);font-family:'Instrument Sans',sans-serif;transition:all .15s}
.tab-btn.active{background:var(--surface2);color:var(--text)}
.sep{height:1px;background:var(--border);margin:16px 0}
.tag{font-family:'DM Mono',monospace;font-size:10px;background:var(--surface2);border:1px solid var(--border);padding:2px 7px;border-radius:4px;color:var(--muted)}
.green-dot{display:inline-block;width:7px;height:7px;background:var(--green);border-radius:50%;margin-right:4px}

/* ── RADAR ── */
.radar-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:10px;transition:border-color .15s}
.radar-card:hover{border-color:var(--border2)}
.radar-card.novo{border-left:3px solid var(--accent)}
.radar-card.visto{opacity:.65}
.radar-municipio{font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:var(--text)}
.radar-estado{font-family:'DM Mono',monospace;font-size:12px;color:var(--muted);margin-left:8px}
.radar-meta{font-size:12px;color:var(--muted);margin-top:3px;margin-bottom:10px}
.radar-trecho{font-size:12px;color:var(--text);background:var(--surface2);border:1px solid var(--border);padding:10px 14px;border-radius:8px;line-height:1.7;margin-bottom:10px;white-space:pre-wrap}
</style>
</head>
<body>
<div class="layout">

<!-- SIDEBAR -->
<nav class="sidebar">
  <div class="logo-area">
    <div class="logo-name">CRM Consignado</div>
    <div class="logo-tag">Juliane · Gestão de carteira</div>
  </div>
  <div class="nav">
    <div class="nav-section">Principal</div>
    <button class="nav-btn active" onclick="showPage('dashboard',this)" data-page="dashboard"><span class="nav-icon">◈</span> Dashboard</button>
    <button class="nav-btn" onclick="showPage('novo',this)" data-page="novo"><span class="nav-icon">+</span> Novo cliente</button>
    <button class="nav-btn" onclick="showPage('lista',this)" data-page="lista"><span class="nav-icon">≡</span> Clientes</button>
    <div class="nav-section">Acompanhamento</div>
    <button class="nav-btn" onclick="showPage('retornos',this)" data-page="retornos" id="nav-retornos">
      <span class="nav-icon">◷</span> Retornos
      <span class="nav-badge" id="badge-retorno" style="display:none">0</span>
    </button>
    <button class="nav-btn" onclick="showPage('mensagens',this)" data-page="mensagens" id="nav-mensagens">
      <span class="nav-icon">◻</span> Mensagens
      <span class="nav-badge" id="badge-msg" style="display:none">0</span>
    </button>
    <div class="nav-section">Ferramentas</div>
    <button class="nav-btn" onclick="showPage('radar',this)" data-page="radar" id="nav-radar">
      <span class="nav-icon">📡</span> Radar Reajustes
      <span class="nav-badge" id="badge-radar" style="display:none">0</span>
    </button>
    <button class="nav-btn" onclick="showPage('historico',this)" data-page="historico"><span class="nav-icon">📋</span> Histórico disparos</button>
    <button class="nav-btn" onclick="showPage('disparos',this)" data-page="disparos"><span class="nav-icon">⚡</span> Disparos em massa</button>
    <button class="nav-btn" onclick="showPage('importar',this)" data-page="importar"><span class="nav-icon">↓</span> Importar planilha</button>
  </div>
  <div class="sidebar-footer">
    <div class="sidebar-footer-text" id="sf-total">Carregando...</div>
  </div>
</nav>

<!-- MAIN -->
<main class="main"><div class="main-inner">

<!-- DASHBOARD -->
<div id="page-dashboard" class="page active">
  <div class="page-header"><div class="page-title">Dashboard</div><div class="page-sub" id="dash-date"></div></div>
  <div class="metrics">
    <div class="metric"><div class="metric-label">Total de clientes</div><div class="metric-value" id="m-total">0</div><div class="metric-accent">◈</div></div>
    <div class="metric"><div class="metric-label">Fecharam</div><div class="metric-value c-green" id="m-fechou">0</div><div class="metric-accent">✓</div></div>
    <div class="metric"><div class="metric-label">Em negociação</div><div class="metric-value c-amber" id="m-negoc">0</div><div class="metric-accent">◷</div></div>
    <div class="metric"><div class="metric-label">Retornos urgentes</div><div class="metric-value c-red" id="m-urgentes">0</div><div class="metric-accent">!</div></div>
  </div>
  <div class="dash-section-title">Retornos urgentes (próximos 3 dias)</div>
  <div id="dash-retornos"></div>
</div>

<!-- NOVO CLIENTE -->
<div id="page-novo" class="page">
  <div class="page-header"><div class="page-title" id="form-title">Novo cliente</div><div class="page-sub" id="form-sub">Preencha os dados do cliente</div></div>
  <div class="card">
    <div class="form-grid">
      <div class="fg full"><label>Nome completo *</label><input type="text" id="f-nome" placeholder="Nome do cliente" style="font-size:15px;padding:11px 14px"></div>
      <div class="fg"><label>CPF</label><input type="text" id="f-cpf" placeholder="000.000.000-00" oninput="maskCPF(this)"></div>
      <div class="fg"><label>Telefone 1</label><input type="text" id="f-tel1" placeholder="(45) 99999-9999"></div>
      <div class="fg"><label>Telefone 2</label><input type="text" id="f-tel2" placeholder="(45) 99999-9999"></div>
      <div class="fg"><label>Convênio</label>
        <select id="f-convenio" onchange="togglePrefeitura()">
          <option value="">Selecione...</option><option>Prefeitura</option><option>INSS</option>
          <option>Governo Estadual</option><option>Forças Armadas</option><option>Privado</option><option>Outro</option>
        </select>
      </div>
      <div class="fg" id="grupo-prefeitura" style="display:none"><label>Qual prefeitura?</label><input type="text" id="f-prefeitura" placeholder="Ex: Foz do Iguaçu"></div>
      <div class="fg"><label>Margem disponível (R$)</label><input type="text" id="f-margem" placeholder="0,00"></div>
      <div class="fg"><label>Data da consulta</label><input type="date" id="f-data-consulta"></div>
      <div class="fg"><label>Data de retorno</label><input type="date" id="f-data-retorno"></div>
      <div class="fg"><label>Status</label>
        <select id="f-fechou"><option value="nao">Em negociação</option><option value="sim">Fechou</option><option value="carteira">Carteira</option></select>
      </div>
      <div class="fg"><label>Motivo do retorno</label>
        <select id="f-motivo">
          <option value="">Selecione...</option><option>Abertura de margem</option><option>Refinanciamento</option>
          <option>Portabilidade</option><option>Novo produto</option><option>Follow-up</option><option>Outro</option>
        </select>
      </div>
      <div class="fg full"><label>Observações</label><textarea id="f-obs" placeholder="Anotações importantes sobre o cliente..."></textarea></div>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="salvarCliente()">Salvar cliente</button>
      <button class="btn btn-ghost" onclick="limparForm()">Limpar</button>
      <button class="btn btn-ghost" id="btn-cancelar-edit" style="display:none" onclick="cancelarEdicao()">Cancelar edição</button>
    </div>
  </div>
</div>

<!-- LISTA -->
<div id="page-lista" class="page">
  <div class="page-header"><div class="page-title">Clientes</div></div>
  <div class="filter-bar">
    <input type="text" id="busca" placeholder="Buscar por nome, CPF, telefone ou convênio..." oninput="filtrarLista()">
    <select id="filtro-status" onchange="filtrarLista()">
      <option value="">Todos os status</option><option value="nao">Em negociação</option><option value="sim">Fecharam</option><option value="carteira">Carteira</option>
    </select>
    <select id="filtro-convenio" onchange="filtrarLista()">
      <option value="">Todos os convênios</option><option>Prefeitura</option><option>INSS</option>
      <option>Governo Estadual</option><option>Forças Armadas</option><option>Privado</option><option>Outro</option>
    </select>
    <span class="results-count" id="results-count"></span>
  </div>
  <div id="lista-clientes" class="client-list"></div>
  <div id="paginacao" class="pagination"></div>
</div>

<!-- RETORNOS -->
<div id="page-retornos" class="page">
  <div class="page-header"><div class="page-title">Retornos</div><div class="page-sub">Agendamentos e follow-ups</div></div>
  <div class="tabs">
    <button class="tab-btn active" onclick="filtroRetorno='urgentes';renderRetornos();setTabActive(this)">Urgentes</button>
    <button class="tab-btn" onclick="filtroRetorno='todos';renderRetornos();setTabActive(this)">Todos</button>
    <button class="tab-btn" onclick="filtroRetorno='sem';renderRetornos();setTabActive(this)">Sem data</button>
  </div>
  <div id="lista-retornos"></div>
</div>

<!-- MENSAGENS -->
<div id="page-mensagens" class="page">
  <div class="page-header"><div class="page-title">Mensagens</div><div class="page-sub">WhatsApp integrado</div></div>
  <div class="chat-layout">
    <div class="chat-list-col">
      <div class="chat-list-header">Conversas</div>
      <div class="chat-list-body" id="msg-lista"><div class="empty"><div class="empty-icon">◻</div><div class="empty-text">Nenhuma conversa ainda</div></div></div>
    </div>
    <div class="chat-win" id="chat-win">
      <div class="chat-win-empty" id="chat-empty"><div style="font-size:32px;opacity:.2">◻</div><div style="font-size:13px">Selecione uma conversa</div></div>
      <div id="chat-open" style="display:none;flex-direction:column;height:100%">
        <div class="cw-header">
          <div><div class="cw-contact-name" id="chat-nome"></div><div class="cw-contact-num" id="chat-num"></div></div>
        </div>
        <div id="chat-perfil" style="display:none;overflow-y:auto;max-height:160px;flex-shrink:0"></div>
        <div class="cw-body" id="chat-msgs"></div>
        <div class="cw-footer">
          <input type="text" id="chat-input" placeholder="Digite uma mensagem..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();enviarResposta()}">
          <button class="btn btn-primary" onclick="enviarResposta()">Enviar</button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- RADAR DE REAJUSTES -->
<div id="page-radar" class="page">
  <div class="page-header">
    <div class="page-title">📡 Radar de Reajustes</div>
    <div class="page-sub">Reajustes salariais detectados em prefeituras via Diário Oficial — atualiza todo dia às 7h</div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px">
    <div class="tabs" style="margin-bottom:0">
      <button class="tab-btn active" onclick="filtroRadar='novos';renderRadar();setTabActive(this)">🔴 Novos</button>
      <button class="tab-btn" onclick="filtroRadar='todos';renderRadar();setTabActive(this)">Todos</button>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input type="text" id="radar-busca" placeholder="Município ou estado..." oninput="renderRadar()" style="width:200px">
      <select id="radar-estado" onchange="renderRadar()" style="width:90px">
        <option value="">UF</option>
        <option>AC</option><option>AL</option><option>AM</option><option>AP</option><option>BA</option>
        <option>CE</option><option>DF</option><option>ES</option><option>GO</option><option>MA</option>
        <option>MG</option><option>MS</option><option>MT</option><option>PA</option><option>PB</option>
        <option>PE</option><option>PI</option><option>PR</option><option>RJ</option><option>RN</option>
        <option>RO</option><option>RR</option><option>RS</option><option>SC</option><option>SE</option>
        <option>SP</option><option>TO</option>
      </select>
      <button class="btn btn-ghost btn-sm" onclick="marcarTodosVistos()">✓ Marcar todos como visto</button>
    </div>
  </div>
  <div id="radar-lista"></div>
</div>

<!-- HISTÓRICO -->
<div id="page-historico" class="page">
  <div class="page-header"><div class="page-title">Histórico de disparos</div><div class="page-sub">Registro de todos os envios em massa</div></div>
  <div id="historico-lista"></div>
</div>

<!-- DISPAROS -->
<div id="page-disparos" class="page">
  <div class="page-header"><div class="page-title">Disparos em massa</div><div class="page-sub">Envio via templates aprovados pela Meta</div></div>
  <div style="display:flex;gap:8px;margin-bottom:16px">
    <button id="aba-carteira" onclick="trocarAbaDisparo('carteira')" class="btn btn-primary" style="font-size:13px">📋 Da carteira</button>
    <button id="aba-colar" onclick="trocarAbaDisparo('colar')" class="btn" style="font-size:13px;background:var(--surface2);color:var(--text)">📋 Colar números</button>
  </div>
  <div class="card" id="disparo-config">
    <div class="card-title">⚡ Configurar disparo</div>
    <div class="form-grid">
      <div class="fg"><label>Template aprovado</label>
        <select id="d-template">
          <option value="aumento_margem_foz">aumento_margem_foz — Prefeitura de Foz</option>
          <option value="credito_consignado_servidores">credito_consignado_servidores — Servidores Públicos</option>
          <option value="aumento_margem_geral">aumento_margem_geral — Geral</option>
          <option value="consignado_convenios">consignado_convenios — Convênios</option>
          <option value="consigandos_para_servidores_botao">consigandos_para_servidores_botao — Servidores c/ Botão</option>
        </select>
      </div>
      <div class="fg"><label>Intervalo entre mensagens</label>
        <select id="d-intervalo">
          <option value="30">30 segundos (mais seguro)</option><option value="20">20 segundos</option>
          <option value="10">10 segundos (mais risco)</option><option value="60">60 segundos (mais cauteloso)</option>
        </select>
      </div>
      <div class="fg"><label>Prefeitura / Órgão</label><select id="d-prefeitura-sel" onchange="filtrarParaDisparo()"><option value="">Todos os convênios</option></select></div>
      <div class="fg"><label>Filtrar por status</label>
        <select id="d-status" onchange="filtrarParaDisparo()">
          <option value="">Todos</option><option value="nao">Em negociação</option><option value="sim">Fecharam</option><option value="carteira">Carteira</option>
        </select>
      </div>
      <div class="fg full"><label>Busca por nome</label><input type="text" id="d-busca" placeholder="Filtrar por nome..." oninput="filtrarParaDisparo()"></div>
    </div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <div style="display:flex;align-items:center;gap:12px">
        <input type="checkbox" id="d-selecionar-todos" onchange="toggleTodos(this)" style="width:16px;height:16px;cursor:pointer">
        <label for="d-selecionar-todos" style="font-size:13px;color:var(--text);text-transform:none;letter-spacing:0;cursor:pointer">Selecionar todos</label>
      </div>
      <span id="d-count" style="font-family:'DM Mono',monospace;font-size:12px;color:var(--muted)">0 selecionados</span>
    </div>
    <div id="d-lista" style="max-height:340px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;margin-bottom:16px"></div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="iniciarDisparo()" id="btn-disparar">⚡ Iniciar disparo</button>
      <span style="font-size:12px;color:var(--muted)">Apenas clientes com telefone cadastrado aparecem na lista</span>
    </div>
  </div>
  <div class="card" id="disparo-colar" style="display:none">
    <div class="card-title">📋 Disparar para números colados</div>
    <div class="form-grid">
      <div class="fg"><label>Template aprovado</label>
        <select id="colar-template">
          <option value="aumento_margem_foz">aumento_margem_foz — Prefeitura de Foz</option>
          <option value="credito_consignado_servidores">credito_consignado_servidores — Servidores Públicos</option>
          <option value="aumento_margem_geral">aumento_margem_geral — Geral</option>
          <option value="consignado_convenios">consignado_convenios — Convênios</option>
          <option value="consigandos_para_servidores_botao">consigandos_para_servidores_botao — Servidores c/ Botão</option>
        </select>
      </div>
      <div class="fg"><label>Intervalo entre mensagens</label>
        <select id="colar-intervalo">
          <option value="30">30 segundos (mais seguro)</option><option value="20">20 segundos</option>
          <option value="10">10 segundos (mais risco)</option><option value="60">60 segundos (mais cauteloso)</option>
        </select>
      </div>
      <div class="fg"><label>Nome padrão (usado no template)</label><input type="text" id="colar-nome" placeholder="Ex: Servidor" value="Servidor"></div>
    </div>
    <div class="fg full" style="margin-top:12px">
      <label>Cole os números aqui (um por linha, ou separados por vírgula)</label>
      <textarea id="colar-numeros" rows="8" placeholder="45999990001&#10;45999990002, João Silva&#10;45999990003, Maria Santos" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px;color:var(--text);font-family:'DM Mono',monospace;font-size:13px;resize:vertical"></textarea>
    </div>
    <div style="display:flex;align-items:center;gap:16px;margin-top:12px">
      <button class="btn btn-primary" onclick="iniciarDisparoColar()">⚡ Iniciar disparo</button>
      <span id="colar-count" style="font-size:13px;color:var(--muted)">0 números detectados</span>
    </div>
  </div>
  <div class="card" id="disparo-progresso" style="display:none">
    <div class="card-title">📡 Disparo em andamento</div>
    <div style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px">
        <span style="font-size:13px;color:var(--muted)" id="prog-texto">Iniciando...</span>
        <span style="font-family:'DM Mono',monospace;font-size:12px;color:var(--text)" id="prog-nums">0/0</span>
      </div>
      <div style="background:var(--surface2);border-radius:20px;height:8px;overflow:hidden">
        <div id="prog-bar" style="height:100%;background:var(--accent);border-radius:20px;width:0%;transition:width .4s"></div>
      </div>
    </div>
    <div style="display:flex;gap:16px;margin-bottom:16px">
      <div class="metric" style="flex:1;padding:12px 16px"><div class="metric-label">Enviados</div><div class="metric-value c-green" id="prog-enviados">0</div></div>
      <div class="metric" style="flex:1;padding:12px 16px"><div class="metric-label">Erros</div><div class="metric-value c-red" id="prog-erros">0</div></div>
      <div class="metric" style="flex:1;padding:12px 16px"><div class="metric-label">Restantes</div><div class="metric-value c-amber" id="prog-restantes">0</div></div>
    </div>
    <div id="prog-log" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;max-height:200px;overflow-y:auto;font-family:'DM Mono',monospace;font-size:11px;color:var(--muted)"></div>
    <div class="btn-row" style="margin-top:16px">
      <button class="btn btn-danger" onclick="cancelarDisparo()" id="btn-cancelar-disparo">✕ Cancelar disparo</button>
    </div>
  </div>
</div>

<!-- IMPORTAR -->
<div id="page-importar" class="page">
  <div class="page-header"><div class="page-title">Importar planilha</div><div class="page-sub">Excel (.xlsx, .xls) ou CSV</div></div>
  <div class="card">
    <div class="drop-area" onclick="document.getElementById('file-input').click()">
      <input type="file" id="file-input" style="display:none" accept=".xlsx,.xls,.csv" onchange="carregarArquivo(this)">
      <div class="drop-icon">📂</div><div class="drop-label">Clique para selecionar o arquivo</div><div class="drop-hint">Aceita .xlsx, .xls, .csv</div>
    </div>
    <div id="seletor-abas" style="display:none" class="card" style="background:var(--amber-dim);border-color:#F59E0B40">
      <div style="font-size:12px;font-weight:600;color:var(--amber-text);margin-bottom:8px">📋 Múltiplas abas detectadas</div>
      <div style="display:flex;align-items:center;gap:10px"><label>Selecionar aba:</label><select id="select-aba" style="width:220px"></select></div>
    </div>
    <div id="import-step2" style="display:none">
      <div class="sep"></div>
      <div class="card-title">Mapeie as colunas</div>
      <p style="font-size:12px;color:var(--muted);margin-bottom:16px">Relacione cada campo do CRM à coluna correspondente na planilha.</p>
      <div class="col-map-grid" id="col-map"></div>
      <div class="card-title">Prévia (5 primeiros registros)</div>
      <div class="preview-wrap"><table class="prev" id="preview-table"></table></div>
      <div class="btn-row">
        <button class="btn btn-primary" onclick="importarDados()">↓ Importar dados</button>
        <button class="btn btn-ghost" onclick="cancelarImport()">Cancelar</button>
      </div>
    </div>
  </div>
</div>

</div></main></div>

<div class="toast" id="toast"></div>

<script>
// ── STATE ──────────────────────────────────────────────────────────────────────
let clientes = [];
let editId = null;
let filtroRetorno = 'urgentes';
let conversas = {};
let chatAtual = null;
let paginaAtual = 1;
const POR_PAGINA = 50;
let listaFiltrada = [];
let dadosImport = [], colunasImport = [];
let reajustesData = [];
let filtroRadar = 'novos';

// ── INIT ───────────────────────────────────────────────────────────────────────
async function init() {
  document.getElementById('f-data-consulta').value = hoje();
  const d = new Date();
  document.getElementById('dash-date').textContent =
    d.toLocaleDateString('pt-BR',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  await carregarClientes();
  await carregarMensagens();
  await carregarRadar();
  setInterval(tickBadges, 30000);
  setInterval(carregarRadar, 60000);
  setInterval(async () => {
    if (document.getElementById('page-mensagens').classList.contains('active')) {
      await carregarMensagens(); if (chatAtual) renderChat();
    } else {
      try { const r = await fetch('/api/mensagens'); conversas = await r.json(); atualizarBadgeMsg(); } catch(e){}
    }
  }, 5000);
}

async function carregarClientes() {
  const r = await fetch('/api/clientes');
  const d = await r.json();
  clientes = d.clientes || [];
  renderDashboard(); tickBadges();
  document.getElementById('sf-total').textContent = `${clientes.length} clientes`;
}

function hoje() { return new Date().toISOString().split('T')[0]; }
function diasAte(data) { if (!data) return null; const d=new Date(data+'T00:00:00'),t=new Date(hoje()+'T00:00:00'); return Math.round((d-t)/86400000); }
function fmt(v) { return v||'—'; }
function fmtTel(t) { if(!t)return'—'; const d=t.replace(/\D/g,''); if(d.length===11)return`(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`; if(d.length===10)return`(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`; return t; }

// ── TOAST ─────────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, type='success') {
  const el=document.getElementById('toast');
  el.textContent=(type==='success'?'✓ ':type==='error'?'✕ ':'')+msg;
  el.className=`toast ${type} show`;
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>el.className='toast',3500);
}

// ── NAVIGATION ────────────────────────────────────────────────────────────────
function showPage(name, btn) {
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  if (btn) btn.classList.add('active');
  if (name==='historico') renderHistorico();
  if (name==='disparos') { popularFiltroDisparo(); filtrarParaDisparo(); }
  if (name==='lista') { paginaAtual=1; filtrarLista(); }
  if (name==='dashboard') renderDashboard();
  if (name==='mensagens') carregarMensagens();
  if (name==='radar') { carregarRadar().then(renderRadar); }
  if (name==='retornos') renderRetornos();
}

function setTabActive(btn) { btn.closest('.tabs').querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); }

function maskCPF(el) {
  let v=el.value.replace(/\D/g,'').slice(0,11);
  if(v.length>9)v=v.replace(/(\d{3})(\d{3})(\d{3})(\d{0,2})/,'$1.$2.$3-$4');
  else if(v.length>6)v=v.replace(/(\d{3})(\d{3})(\d{0,3})/,'$1.$2.$3');
  else if(v.length>3)v=v.replace(/(\d{3})(\d{0,3})/,'$1.$2');
  el.value=v;
}

function togglePrefeitura() {
  document.getElementById('grupo-prefeitura').style.display=document.getElementById('f-convenio').value==='Prefeitura'?'flex':'none';
}

function limparForm() {
  ['f-nome','f-cpf','f-tel1','f-tel2','f-margem','f-obs','f-prefeitura'].forEach(id=>document.getElementById(id).value='');
  ['f-convenio','f-fechou','f-motivo'].forEach(id=>document.getElementById(id).selectedIndex=0);
  document.getElementById('f-data-consulta').value=hoje();
  document.getElementById('f-data-retorno').value='';
  document.getElementById('grupo-prefeitura').style.display='none';
}

function cancelarEdicao() {
  editId=null;
  document.getElementById('form-title').textContent='Novo cliente';
  document.getElementById('form-sub').textContent='Preencha os dados do cliente';
  document.getElementById('btn-cancelar-edit').style.display='none';
  limparForm();
}

async function salvarCliente() {
  const nome=document.getElementById('f-nome').value.trim();
  if(!nome){toast('Informe o nome do cliente','error');return;}
  const c={
    id:editId||Date.now()+Math.random(), nome,
    cpf:document.getElementById('f-cpf').value, tel1:document.getElementById('f-tel1').value,
    tel2:document.getElementById('f-tel2').value, convenio:document.getElementById('f-convenio').value,
    prefeitura:document.getElementById('f-prefeitura').value, margem:document.getElementById('f-margem').value,
    dataConsulta:document.getElementById('f-data-consulta').value, dataRetorno:document.getElementById('f-data-retorno').value,
    fechou:document.getElementById('f-fechou').value, motivo:document.getElementById('f-motivo').value,
    obs:document.getElementById('f-obs').value
  };
  if(editId){const i=clientes.findIndex(x=>x.id===editId);if(i>=0)clientes[i]=c;toast('Cliente atualizado!');}
  else{clientes.push(c);toast('Cliente salvo!');}
  await salvarServidor(); cancelarEdicao(); renderDashboard(); tickBadges();
  document.getElementById('sf-total').textContent=`${clientes.length} clientes`;
}

async function salvarServidor() {
  await fetch('/api/salvar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clientes})});
}

function editarCliente(id) {
  const c=clientes.find(x=>x.id===id);if(!c)return;
  editId=id;
  document.getElementById('f-nome').value=c.nome;document.getElementById('f-cpf').value=c.cpf||'';
  document.getElementById('f-tel1').value=c.tel1||'';document.getElementById('f-tel2').value=c.tel2||'';
  document.getElementById('f-convenio').value=c.convenio||'';togglePrefeitura();
  document.getElementById('f-prefeitura').value=c.prefeitura||'';document.getElementById('f-margem').value=c.margem||'';
  document.getElementById('f-data-consulta').value=c.dataConsulta||'';document.getElementById('f-data-retorno').value=c.dataRetorno||'';
  document.getElementById('f-fechou').value=c.fechou||'nao';document.getElementById('f-motivo').value=c.motivo||'';
  document.getElementById('f-obs').value=c.obs||'';
  document.getElementById('form-title').textContent='Editar cliente';
  document.getElementById('form-sub').textContent=c.nome;
  document.getElementById('btn-cancelar-edit').style.display='inline-flex';
  showPage('novo',document.querySelector('[data-page="novo"]'));window.scrollTo(0,0);
}

async function excluirCliente(id) {
  if(!confirm('Confirma exclusão deste cliente?'))return;
  clientes=clientes.filter(x=>x.id!==id);
  await salvarServidor();filtrarLista();renderDashboard();tickBadges();
  document.getElementById('sf-total').textContent=`${clientes.length} clientes`;
  toast('Cliente excluído');
}

function tickBadges() {
  const n=clientes.filter(c=>{const d=diasAte(c.dataRetorno);return d!==null&&d<=0;}).length;
  const b=document.getElementById('badge-retorno');b.textContent=n;b.style.display=n>0?'inline':'none';
}

function atualizarBadgeMsg() {
  let nl=0;Object.values(conversas).forEach(c=>{nl+=(c.msgs||[]).filter(m=>m.dir==='recv'&&!m.lida).length;});
  const b=document.getElementById('badge-msg');b.textContent=nl;b.style.display=nl>0?'inline':'none';
}

function renderDashboard() {
  document.getElementById('m-total').textContent=clientes.length;
  document.getElementById('m-fechou').textContent=clientes.filter(c=>c.fechou==='sim').length;
  document.getElementById('m-negoc').textContent=clientes.filter(c=>c.fechou==='nao').length;
  const urgentes=clientes.filter(c=>{const d=diasAte(c.dataRetorno);return d!==null&&d<=3;});
  document.getElementById('m-urgentes').textContent=urgentes.length;
  const el=document.getElementById('dash-retornos');
  if(!urgentes.length){el.innerHTML='<div class="empty"><div class="empty-icon">✓</div><div class="empty-text">Nenhum retorno urgente. Tudo em dia!</div></div>';return;}
  el.innerHTML=urgentes.sort((a,b)=>a.dataRetorno.localeCompare(b.dataRetorno)).map(c=>{
    const dias=diasAte(c.dataRetorno);
    const badge=dias<0?`<span class="badge badge-atrasado">Atrasado ${Math.abs(dias)}d</span>`:dias===0?`<span class="badge badge-hoje">Hoje!</span>`:`<span class="badge badge-breve">Em ${dias}d</span>`;
    return `<div class="retorno-card"><div class="rc-left"><div class="rc-nome">${c.nome}</div><div class="rc-detail">${fmtTel(c.tel1)} · ${c.motivo||c.convenio||'Retorno'}</div></div><div class="rc-right"><div class="rc-date">${c.dataRetorno}</div>${badge}<button class="btn btn-edit btn-sm" onclick="editarCliente(${c.id})">✏ Editar</button></div></div>`;
  }).join('');
}

function filtrarLista() {
  const q=(document.getElementById('busca').value||'').toLowerCase();
  const fs=document.getElementById('filtro-status').value;
  const fc=document.getElementById('filtro-convenio').value;
  listaFiltrada=clientes.filter(c=>{
    const match=!q||c.nome.toLowerCase().includes(q)||(c.cpf||'').includes(q)||(c.tel1||'').includes(q)||(c.tel2||'').includes(q)||(c.convenio||'').toLowerCase().includes(q)||(c.prefeitura||'').toLowerCase().includes(q)||(c.obs||'').toLowerCase().includes(q);
    return match&&(!fs||c.fechou===fs)&&(!fc||c.convenio===fc);
  });
  paginaAtual=1;
  document.getElementById('results-count').textContent=`${listaFiltrada.length} resultado${listaFiltrada.length!==1?'s':''}`;
  renderLista();
}

function renderLista() {
  const el=document.getElementById('lista-clientes');
  if(!listaFiltrada.length){el.innerHTML='<div class="empty"><div class="empty-icon">◈</div><div class="empty-text">Nenhum cliente encontrado</div></div>';document.getElementById('paginacao').innerHTML='';return;}
  const totalPag=Math.ceil(listaFiltrada.length/POR_PAGINA),inicio=(paginaAtual-1)*POR_PAGINA,slice=listaFiltrada.slice(inicio,inicio+POR_PAGINA);
  el.innerHTML=slice.map(c=>{
    const dias=diasAte(c.dataRetorno);let retBadge='';
    if(dias!==null){if(dias<0)retBadge=`<span class="badge badge-atrasado">Atrasado ${Math.abs(dias)}d</span>`;else if(dias===0)retBadge=`<span class="badge badge-hoje">Retorno hoje!</span>`;else if(dias<=7)retBadge=`<span class="badge badge-breve">Retorno em ${dias}d</span>`;}
    const sb=c.fechou==='sim'?'badge-fechou':c.fechou==='carteira'?'badge-carteira':'badge-negoc';
    const sl=c.fechou==='sim'?'Fechou':c.fechou==='carteira'?'Carteira':'Em negociação';
    const conv=c.convenio==='Prefeitura'&&c.prefeitura?`Prefeitura · ${c.prefeitura}`:c.convenio||'—';
    return `<div class="client-card"><div class="cc-top"><div class="cc-name">${c.nome}</div><div class="cc-badges"><span class="badge ${sb}">${sl}</span>${retBadge}</div></div><div class="cc-info"><div class="cc-field">CPF: <strong>${fmt(c.cpf)}</strong></div><div class="cc-field">Tel 1: <strong>${fmtTel(c.tel1)}</strong></div><div class="cc-field">Tel 2: <strong>${c.tel2?fmtTel(c.tel2):'—'}</strong></div><div class="cc-field">Convênio: <strong>${conv}</strong></div><div class="cc-field">Margem: <strong>${c.margem?'R$ '+c.margem:'—'}</strong></div><div class="cc-field">Retorno: <strong>${c.dataRetorno||'—'}</strong></div></div>${c.obs?`<div class="cc-obs">${c.obs}</div>`:''}<div class="cc-actions"><button class="btn btn-edit btn-sm" onclick="editarCliente(${c.id})">✏ Editar</button><button class="btn btn-danger btn-sm" onclick="excluirCliente(${c.id})">✕ Excluir</button>${c.tel1?`<button class="btn btn-wpp btn-sm" onclick="abrirChatTel('${c.tel1}','${c.nome}')">💬 WhatsApp</button>`:''}</div></div>`;
  }).join('');
  const pEl=document.getElementById('paginacao');
  if(totalPag<=1){pEl.innerHTML='';return;}
  let pg=`<button class="pg-btn" onclick="irPagina(${paginaAtual-1})" ${paginaAtual===1?'disabled':''}>‹</button>`;
  for(let i=1;i<=totalPag;i++){if(i===1||i===totalPag||Math.abs(i-paginaAtual)<=2)pg+=`<button class="pg-btn ${i===paginaAtual?'active':''}" onclick="irPagina(${i})">${i}</button>`;else if(Math.abs(i-paginaAtual)===3)pg+=`<span class="pg-info">…</span>`;}
  pg+=`<button class="pg-btn" onclick="irPagina(${paginaAtual+1})" ${paginaAtual===totalPag?'disabled':''}>›</button><span class="pg-info">${inicio+1}–${Math.min(inicio+POR_PAGINA,listaFiltrada.length)} de ${listaFiltrada.length}</span>`;
  pEl.innerHTML=pg;
}

function irPagina(n){const t=Math.ceil(listaFiltrada.length/POR_PAGINA);if(n<1||n>t)return;paginaAtual=n;renderLista();document.querySelector('.main').scrollTo(0,0);}

function renderRetornos() {
  const el=document.getElementById('lista-retornos');let lista;
  if(filtroRetorno==='urgentes')lista=clientes.filter(c=>{const d=diasAte(c.dataRetorno);return d!==null&&d<=7;}).sort((a,b)=>a.dataRetorno.localeCompare(b.dataRetorno));
  else if(filtroRetorno==='sem')lista=clientes.filter(c=>!c.dataRetorno);
  else lista=clientes.filter(c=>c.dataRetorno).sort((a,b)=>a.dataRetorno.localeCompare(b.dataRetorno));
  if(!lista.length){el.innerHTML='<div class="empty"><div class="empty-icon">◷</div><div class="empty-text">Nenhum registro nesta categoria</div></div>';return;}
  el.innerHTML=lista.map(c=>{
    const dias=diasAte(c.dataRetorno);let badge='';
    if(dias!==null){if(dias<0)badge=`<span class="badge badge-atrasado">Atrasado ${Math.abs(dias)}d</span>`;else if(dias===0)badge=`<span class="badge badge-hoje">Hoje!</span>`;else if(dias<=7)badge=`<span class="badge badge-breve">Em ${dias}d</span>`;else badge=`<span class="badge badge-ok">Em ${dias}d</span>`;}
    return `<div class="retorno-card"><div class="rc-left"><div class="rc-nome">${c.nome}</div><div class="rc-detail">${fmtTel(c.tel1)} · ${c.convenio||'—'} · ${c.motivo||'Retorno agendado'}</div>${c.obs?`<div class="rc-detail" style="margin-top:3px;font-style:italic">${c.obs}</div>`:''}</div><div class="rc-right">${c.dataRetorno?`<div class="rc-date">${c.dataRetorno}</div>`:''} ${badge}<button class="btn btn-edit btn-sm" onclick="editarCliente(${c.id})">✏ Editar</button></div></div>`;
  }).join('');
}

// ── MENSAGENS ─────────────────────────────────────────────────────────────────
async function carregarMensagens() {
  try{const r=await fetch('/api/mensagens');conversas=await r.json();renderListaMensagens();atualizarBadgeMsg();}catch(e){}
}

function renderListaMensagens() {
  const el=document.getElementById('msg-lista');
  const lista=Object.values(conversas).sort((a,b)=>{const ua=a.msgs?.slice(-1)[0]?.ts||0,ub=b.msgs?.slice(-1)[0]?.ts||0;return ub-ua;});
  if(!lista.length){el.innerHTML='<div class="empty"><div class="empty-icon">◻</div><div class="empty-text">Nenhuma conversa ainda</div></div>';return;}
  el.innerHTML=lista.map(c=>{
    const ultima=c.msgs?.slice(-1)[0],nl=(c.msgs||[]).filter(m=>m.dir==='recv'&&!m.lida).length;
    const hora=ultima?new Date(ultima.ts).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}):'';
    const cli=clientes.find(x=>{const t=x.tel1?.replace(/\D/g,'');return t&&c.numero.endsWith(t);});
    const nome=cli?cli.nome:(c.nome!==c.numero?c.nome:c.numero);
    return `<div class="chat-item ${nl?'unread':''} ${chatAtual===c.numero?'active':''}" onclick="abrirChat('${c.numero}','${nome}')"><div class="ci-header"><span class="ci-name">${nome}${nl?`<span class="ci-badge">${nl}</span>`:''}</span><span class="ci-time">${hora}</span></div><div class="ci-preview">${ultima?.dir==='sent'?'Você: ':''}${ultima?.texto||''}</div></div>`;
  }).join('');
}

function abrirChatTel(tel,nome){
  let num=tel.replace(/\D/g,'');if(num.startsWith('0'))num=num.slice(1);if(!num.startsWith('55'))num='55'+num;if(num.length===12)num=num.slice(0,4)+'9'+num.slice(4);
  showPage('mensagens',document.querySelector('[data-page="mensagens"]'));setTimeout(()=>abrirChat(num,nome),100);
}

function abrirChat(numero,nome){
  chatAtual=numero;
  const cli=clientes.find(c=>{let t=c.tel1?.replace(/\D/g,'')||'';if(t.startsWith('0'))t=t.slice(1);if(!t.startsWith('55'))t='55'+t;if(t.length===12)t=t.slice(0,4)+'9'+t.slice(4);return t===numero;});
  const nomeExibir=cli?cli.nome:(conversas[numero]?.nome||nome);
  document.getElementById('chat-nome').textContent=nomeExibir;
  document.getElementById('chat-num').textContent=numero;
  const perfil=document.getElementById('chat-perfil');
  if(cli){
    const sb=cli.fechou==='sim'?'badge-fechou':cli.fechou==='carteira'?'badge-carteira':'badge-negoc';
    const sl=cli.fechou==='sim'?'Fechou':cli.fechou==='carteira'?'Carteira':'Em negociação';
    perfil.innerHTML=`<div style="padding:12px 16px;border-bottom:1px solid var(--border);background:var(--surface2)"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><span style="font-size:11px;font-family:'DM Mono',monospace;color:var(--muted);text-transform:uppercase;letter-spacing:1px">Cadastro do cliente</span><button class="btn btn-edit btn-sm" onclick="editarCliente(${cli.id})">✏ Editar</button></div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:12px"><div class="cc-field">CPF: <strong>${cli.cpf||'—'}</strong></div><div class="cc-field">Convênio: <strong>${cli.convenio||'—'}${cli.prefeitura?' · '+cli.prefeitura:''}</strong></div><div class="cc-field">Margem: <strong>${cli.margem?'R$ '+cli.margem:'—'}</strong></div><div class="cc-field">Retorno: <strong>${cli.dataRetorno||'—'}</strong></div><div class="cc-field">Status: <span class="badge ${sb}">${sl}</span></div>${cli.obs?`<div class="cc-field" style="grid-column:1/-1">Obs: <strong>${cli.obs}</strong></div>`:''}</div><div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><button class="btn btn-sm" style="background:var(--green-dim);color:var(--green-text);border:1px solid #2ECC7130" onclick="marcarFechou(${cli.id})">✓ Fechou</button><button class="btn btn-sm" style="background:var(--amber-dim);color:var(--amber-text);border:1px solid #F59E0B30" onclick="agendarRetorno(${cli.id})">◷ Agendar retorno</button></div></div>`;
    perfil.style.display='block';
  }else{perfil.innerHTML='';perfil.style.display='none';}
  document.getElementById('chat-empty').style.display='none';
  document.getElementById('chat-open').style.display='flex';
  if(conversas[numero]){conversas[numero].msgs?.forEach(m=>m.lida=true);fetch('/api/mensagens/lidas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({numero})});}
  renderChat();renderListaMensagens();atualizarBadgeMsg();
  document.getElementById('chat-input').focus();
}

async function marcarFechou(id){const c=clientes.find(x=>x.id===id);if(!c)return;c.fechou='sim';await fetch('/api/salvar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clientes:[c]})});toast('Cliente marcado como fechou!');abrirChat(chatAtual,c.nome);}
async function agendarRetorno(id){const data=prompt('Data de retorno (AAAA-MM-DD):');if(!data)return;const c=clientes.find(x=>x.id===id);if(!c)return;c.dataRetorno=data;await fetch('/api/salvar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clientes:[c]})});toast('Retorno agendado!');abrirChat(chatAtual,c.nome);tickBadges();}

function renderChat(){
  const el=document.getElementById('chat-msgs');const conv=conversas[chatAtual];
  if(!conv||!conv.msgs?.length){el.innerHTML='<div class="empty"><div class="empty-text">Nenhuma mensagem ainda</div></div>';return;}
  let ultimaData='';
  el.innerHTML=conv.msgs.map(m=>{
    const d=new Date(m.ts),dataStr=d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric'}),hora=d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
    let sep='';if(dataStr!==ultimaData){ultimaData=dataStr;sep=`<div style="text-align:center;margin:8px 0"><span style="background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:3px 12px;font-family:'DM Mono',monospace;font-size:10px;color:var(--muted)">${dataStr}</span></div>`;}
    return `${sep}<div class="msg-bubble ${m.dir==='recv'?'recv':'sent'}">${m.imagem_id?`<img src="/api/imagem/${m.imagem_id}" style="max-width:100%;border-radius:8px;display:block;margin-bottom:4px" loading="lazy">`:''} ${m.doc_id?`<a href="/api/documento/${m.doc_id}" target="_blank" style="display:inline-flex;align-items:center;gap:6px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 12px;color:var(--blue-text);text-decoration:none;font-size:12px">📄 ${m.doc_nome||'Documento'}</a>`:''} ${m.texto&&!m.texto.startsWith('[IMAGEM:')&&!m.texto.startsWith('[DOCUMENTO:')?m.texto:''}<div class="msg-time">${hora}</div></div>`;
  }).join('');
  el.scrollTop=el.scrollHeight;
}

async function enviarResposta(){
  const input=document.getElementById('chat-input'),msg=input.value.trim();if(!msg||!chatAtual)return;input.value='';
  try{const r=await fetch('/api/whatsapp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({telefone:chatAtual,mensagem:msg,salvar:true})});const d=await r.json();
  if(d.messages||d.ok){if(!conversas[chatAtual])conversas[chatAtual]={numero:chatAtual,nome:chatAtual,msgs:[]};conversas[chatAtual].msgs.push({dir:'sent',texto:msg,ts:Date.now(),lida:true});renderChat();renderListaMensagens();}
  else toast('Erro ao enviar: '+(d.erro||JSON.stringify(d)),'error');}catch(e){toast('Erro de conexão','error');}
}

// ── RADAR DE REAJUSTES ────────────────────────────────────────────────────────
async function carregarRadar() {
  try {
    const r = await fetch('/api/reajustes');
    reajustesData = await r.json();
    atualizarBadgeRadar();
  } catch(e) { console.error('Erro radar:', e); }
}

function atualizarBadgeRadar() {
  const novos = reajustesData.filter(r => !r.visualizado).length;
  const b = document.getElementById('badge-radar');
  if (b) { b.textContent = novos; b.style.display = novos > 0 ? 'inline' : 'none'; }
}

function renderRadar() {
  const el = document.getElementById('radar-lista');
  if (!el) return;
  const busca = (document.getElementById('radar-busca')?.value || '').toLowerCase();
  const estado = document.getElementById('radar-estado')?.value || '';
  let lista = reajustesData.filter(r => {
    if (filtroRadar === 'novos' && r.visualizado) return false;
    if (estado && r.estado !== estado) return false;
    if (busca && !r.municipio.toLowerCase().includes(busca) && !r.estado.toLowerCase().includes(busca)) return false;
    return true;
  });
  if (!lista.length) {
    el.innerHTML = `<div class="empty"><div class="empty-icon">📡</div>
      <div class="empty-text">${filtroRadar === 'novos' ? 'Nenhum reajuste novo ainda.' : 'Nenhum resultado com esses filtros.'}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:8px">O monitor busca no Diário Oficial todo dia às 7h</div></div>`;
    return;
  }
  el.innerHTML = lista.map(r => `
    <div class="radar-card ${r.visualizado ? 'visto' : 'novo'}">
      <div class="cc-top">
        <div>
          <span class="radar-municipio">🏛 ${r.municipio}</span>
          <span class="radar-estado">${r.estado}</span>
          <div class="radar-meta">Publicado em ${r.data_publicacao} · detectado ${r.data_detectado} · ${r.fonte}</div>
        </div>
        <div class="cc-badges">
          ${!r.visualizado ? '<span class="badge" style="background:var(--accent);color:#fff;border:none">NOVO</span>' : '<span class="badge badge-ok">Visto</span>'}
        </div>
      </div>
      ${r.trecho ? `<div class="radar-trecho">${r.trecho}</div>` : ''}
      <div class="cc-actions">
        <a href="${r.url}" target="_blank" class="btn btn-ghost btn-sm">🔗 Ver no Diário Oficial</a>
        <button class="btn btn-primary btn-sm" onclick="dispararParaMunicipio('${r.municipio.replace(/'/g,"\\'")}','${r.estado}',${r.id})">⚡ Disparar campanha</button>
        ${!r.visualizado ? `<button class="btn btn-edit btn-sm" onclick="marcarVisto(${r.id})">✓ Marcar como visto</button>` : ''}
      </div>
    </div>`).join('');
}

async function marcarVisto(id) {
  await fetch('/api/reajustes/visualizar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  const r=reajustesData.find(x=>x.id===id);if(r)r.visualizado=true;
  renderRadar();atualizarBadgeRadar();
}

async function marcarTodosVistos() {
  const novos=reajustesData.filter(r=>!r.visualizado);
  for(const r of novos){await fetch('/api/reajustes/visualizar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:r.id})});r.visualizado=true;}
  renderRadar();atualizarBadgeRadar();toast(`${novos.length} reajustes marcados como vistos`);
}

function dispararParaMunicipio(municipio, estado, reajusteId) {
  showPage('disparos',document.querySelector('[data-page="disparos"]'));
  setTimeout(()=>{
    popularFiltroDisparo();filtrarParaDisparo();
    const sel=document.getElementById('d-prefeitura-sel');
    if(sel){const op=[...sel.options].find(o=>o.text.toLowerCase().includes(municipio.toLowerCase()));if(op)sel.value=op.value;}
    filtrarParaDisparo();
    toast(`Filtrando clientes de ${municipio}/${estado} — escolha o template e dispare!`);
  },300);
  marcarVisto(reajusteId);
}

// ── HISTÓRICO ─────────────────────────────────────────────────────────────────
async function renderHistorico() {
  const el=document.getElementById('historico-lista');el.innerHTML='<div class="empty"><div class="loading"></div></div>';
  try{
    const r=await fetch('/api/disparos/historico'),lista=await r.json();
    if(!lista.length){el.innerHTML='<div class="empty"><div class="empty-icon">📋</div><div class="empty-text">Nenhum disparo realizado ainda</div></div>';return;}
    el.innerHTML=lista.map(d=>`<div class="card" style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><div><div style="font-family:'Syne',sans-serif;font-weight:700;font-size:15px">${d.template}</div><div style="font-family:'DM Mono',monospace;font-size:11px;color:var(--muted)">${d.data_hora}</div></div><div style="display:flex;gap:12px"><div style="text-align:center"><div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--green-text)">${d.enviados}</div><div style="font-size:10px;color:var(--muted)">enviados</div></div><div style="text-align:center"><div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--red-text)">${d.erros}</div><div style="font-size:10px;color:var(--muted)">erros</div></div><div style="text-align:center"><div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--text)">${d.total}</div><div style="font-size:10px;color:var(--muted)">total</div></div></div></div><details><summary style="cursor:pointer;font-size:12px;color:var(--muted);font-family:'DM Mono',monospace">Ver log detalhado</summary><div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:8px;max-height:200px;overflow-y:auto;font-family:'DM Mono',monospace;font-size:11px">${(d.log||[]).map(l=>`<div style="color:${l.ok?'var(--green-text)':'var(--red-text)'};margin-bottom:2px">${l.ok?'✓':'✕'} ${l.nome} (${l.tel}) ${l.ok?'— enviado':'— '+l.erro}</div>`).join('')}</div></details></div>`).join('');
  }catch(e){el.innerHTML='<div class="empty"><div class="empty-text">Erro ao carregar histórico</div></div>';}
}

// ── DISPAROS ──────────────────────────────────────────────────────────────────
let clientesParaDisparar=[],todosDisparoFiltrado=[],disparoAtivo=false;

function popularFiltroDisparo(){
  const orgaos=new Set();clientes.forEach(c=>{if(c.convenio==='Prefeitura'&&c.prefeitura)orgaos.add('Prefeitura · '+c.prefeitura.trim());else if(c.convenio)orgaos.add(c.convenio);});
  const sel=document.getElementById('d-prefeitura-sel');
  sel.innerHTML='<option value="">Todos os convênios</option>'+[...orgaos].sort().map(o=>`<option value="${o}">${o}</option>`).join('');
}

function filtrarParaDisparo(){
  const orgaoSel=document.getElementById('d-prefeitura-sel').value,status=document.getElementById('d-status').value,busca=(document.getElementById('d-busca').value||'').toLowerCase();
  todosDisparoFiltrado=clientes.filter(c=>{
    if(!c.tel1)return false;
    let og=c.convenio==='Prefeitura'&&c.prefeitura?'Prefeitura · '+c.prefeitura.trim():c.convenio||'';
    if(orgaoSel&&og!==orgaoSel)return false;
    if(status&&c.fechou!==status)return false;
    if(busca&&!c.nome.toLowerCase().includes(busca))return false;
    return true;
  });
  renderListaDisparo();
}

function renderListaDisparo(){
  const el=document.getElementById('d-lista');
  if(!todosDisparoFiltrado.length){el.innerHTML='<div class="empty" style="padding:24px"><div class="empty-text">Nenhum cliente encontrado</div></div>';atualizarContadorDisparo();return;}
  el.innerHTML=todosDisparoFiltrado.map(c=>{const sel=clientesParaDisparar.some(x=>x.id===c.id);return`<div style="display:flex;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid var(--border)"><input type="checkbox" ${sel?'checked':''} onchange="toggleCliente(this,${c.id})" style="width:15px;height:15px;cursor:pointer;flex-shrink:0"><div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600;color:var(--text)">${c.nome}</div><div style="font-size:11px;color:var(--muted);font-family:'DM Mono',monospace">${fmtTel(c.tel1)} · ${c.convenio||'—'}${c.prefeitura?' · '+c.prefeitura:''}</div></div><div style="font-size:11px;color:var(--accent);font-family:'DM Mono',monospace">Olá, ${c.nome.split(' ')[0]}!</div></div>`;}).join('');
  atualizarContadorDisparo();
}

function toggleCliente(cb,id){const c=clientes.find(x=>x.id===id);if(!c)return;if(cb.checked){if(!clientesParaDisparar.some(x=>x.id===id))clientesParaDisparar.push(c);}else{clientesParaDisparar=clientesParaDisparar.filter(x=>x.id!==id);document.getElementById('d-selecionar-todos').checked=false;}atualizarContadorDisparo();}
function toggleTodos(cb){if(cb.checked)clientesParaDisparar=[...todosDisparoFiltrado];else clientesParaDisparar=[];renderListaDisparo();}
function atualizarContadorDisparo(){document.getElementById('d-count').textContent=`${clientesParaDisparar.length} selecionados`;}
function trocarAbaDisparo(aba){
  document.getElementById('disparo-config').style.display=aba==='carteira'?'block':'none';
  document.getElementById('disparo-colar').style.display=aba==='colar'?'block':'none';
  document.getElementById('aba-carteira').className=aba==='carteira'?'btn btn-primary':'btn';
  document.getElementById('aba-carteira').style.background=aba==='carteira'?'':'var(--surface2)';
  document.getElementById('aba-carteira').style.color=aba==='carteira'?'':'var(--text)';
  document.getElementById('aba-colar').className=aba==='colar'?'btn btn-primary':'btn';
  document.getElementById('aba-colar').style.background=aba==='colar'?'':'var(--surface2)';
  document.getElementById('aba-colar').style.color=aba==='colar'?'':'var(--text)';
}

function extrairContatos(texto){
  const nomeDefault=document.getElementById('colar-nome').value.trim()||'Servidor',contatos=[];
  for(const linha of texto.split(/[\n\r]+/).map(l=>l.trim()).filter(l=>l)){
    const partes=linha.split(/[,\t]/).map(p=>p.trim());let numero='',nome=nomeDefault;
    for(const p of partes){const an=p.replace(/\D/g,'');if(an.length>=10&&an.length<=13)numero=an;else if(p.length>1)nome=p.split(' ')[0];}
    if(numero)contatos.push({tel1:numero,nome});
  }
  return contatos;
}

document.addEventListener('DOMContentLoaded',()=>{
  const ta=document.getElementById('colar-numeros');
  if(ta)ta.addEventListener('input',()=>{const c=extrairContatos(ta.value);document.getElementById('colar-count').textContent=c.length+' números detectados';});
});

async function iniciarDisparoColar(){
  const texto=document.getElementById('colar-numeros').value,contatos=extrairContatos(texto);
  const template=document.getElementById('colar-template').value,intervalo=parseInt(document.getElementById('colar-intervalo').value);
  if(!contatos.length){toast('Nenhum número válido detectado','error');return;}
  if(!confirm(`Confirma disparo do template "${template}" para ${contatos.length} contatos?\nIntervalo: ${intervalo}s`))return;
  document.getElementById('disparo-colar').style.display='none';
  document.getElementById('disparo-progresso').style.display='block';
  const total=contatos.length;let enviados=0,erros=0;
  function addLog(msg,tipo='ok'){const el=document.getElementById('prog-log'),cor=tipo==='ok'?'var(--green-text)':tipo==='erro'?'var(--red-text)':'var(--muted)';el.innerHTML+=`<div style="color:${cor};margin-bottom:2px">${new Date().toLocaleTimeString('pt-BR')} — ${msg}</div>`;el.scrollTop=el.scrollHeight;}
  function atualizarProgresso(){const pct=Math.round(((enviados+erros)/total)*100);document.getElementById('prog-bar').style.width=pct+'%';document.getElementById('prog-nums').textContent=`${enviados+erros}/${total}`;document.getElementById('prog-enviados').textContent=enviados;document.getElementById('prog-erros').textContent=erros;document.getElementById('prog-restantes').textContent=total-enviados-erros;document.getElementById('prog-texto').textContent=pct<100?`Enviando... ${pct}%`:'Concluído!';}
  addLog(`Iniciando: ${total} números · ${template}`,'info');
  for(let i=0;i<contatos.length;i++){
    let cancelar=false;try{const s=await fetch('/api/disparo/status').then(r=>r.json());cancelar=s.cancelar;}catch(e){}
    if(cancelar){addLog('Cancelado.','erro');break;}
    const c=contatos[i];
    try{const r=await fetch('/api/disparo/enviar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({telefone:c.tel1,template,nome:c.nome})});const d=await r.json();
    if(d.messages||d.ok){enviados++;addLog(`✓ ${c.tel1} (${c.nome})`);}else{erros++;addLog(`✕ ${c.tel1} — ${d.erro||JSON.stringify(d)}`,'erro');}}catch(e){erros++;addLog(`✕ ${c.tel1} — erro de conexão`,'erro');}
    atualizarProgresso();
    if(i<contatos.length-1){addLog(`Aguardando ${intervalo}s...`,'info');await new Promise(r=>setTimeout(r,intervalo*1000));}
  }
  addLog(`Finalizado. ✓ ${enviados} · ✕ ${erros}`,'ok');
}

async function iniciarDisparo(){
  if(!clientesParaDisparar.length){toast('Selecione pelo menos um cliente','error');return;}
  const template=document.getElementById('d-template').value,intervalo=parseInt(document.getElementById('d-intervalo').value);
  if(!confirm(`Confirma disparo do template "${template}" para ${clientesParaDisparar.length} clientes?\nIntervalo: ${intervalo}s`))return;
  document.getElementById('disparo-config').style.display='none';
  document.getElementById('disparo-progresso').style.display='block';disparoAtivo=true;
  const total=clientesParaDisparar.length;let enviados=0,erros=0;
  function addLog(msg,tipo='ok'){const el=document.getElementById('prog-log'),cor=tipo==='ok'?'var(--green-text)':tipo==='erro'?'var(--red-text)':'var(--muted)';el.innerHTML+=`<div style="color:${cor};margin-bottom:2px">${new Date().toLocaleTimeString('pt-BR')} — ${msg}</div>`;el.scrollTop=el.scrollHeight;}
  function atualizarProgresso(){const pct=Math.round(((enviados+erros)/total)*100);document.getElementById('prog-bar').style.width=pct+'%';document.getElementById('prog-nums').textContent=`${enviados+erros}/${total}`;document.getElementById('prog-enviados').textContent=enviados;document.getElementById('prog-erros').textContent=erros;document.getElementById('prog-restantes').textContent=total-enviados-erros;document.getElementById('prog-texto').textContent=pct<100?`Enviando... ${pct}%`:'Concluído!';}
  addLog(`Iniciando: ${total} clientes · ${template}`,'info');const logDetalhado=[];
  for(let i=0;i<clientesParaDisparar.length;i++){
    let cancelar=false;try{const s=await fetch('/api/disparo/status').then(r=>r.json());cancelar=s.cancelar;}catch(e){}
    if(cancelar){addLog('Cancelado.','erro');break;}
    const c=clientesParaDisparar[i],nomeUsar=c.nome.split(' ')[0];
    try{const r=await fetch('/api/disparo/enviar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({telefone:c.tel1,template,nome:nomeUsar})});const d=await r.json();
    if(d.messages||d.ok){enviados++;logDetalhado.push({ok:true,nome:c.nome,tel:c.tel1});addLog(`✓ ${c.nome}`);}else{erros++;const motivo=d.erro?JSON.parse(d.erro)?.error?.message||d.erro:JSON.stringify(d);logDetalhado.push({ok:false,nome:c.nome,tel:c.tel1,erro:motivo});addLog(`✕ ${c.nome} — ${motivo}`,'erro');}}catch(e){erros++;addLog(`✕ ${c.nome} — erro de conexão`,'erro');}
    atualizarProgresso();
    if(i<clientesParaDisparar.length-1){addLog(`Aguardando ${intervalo}s...`,'info');await new Promise(r=>setTimeout(r,intervalo*1000));}
  }
  addLog(`Finalizado. ✓ ${enviados} · ✕ ${erros}`,'ok');
  await fetch('/api/disparos/salvar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template,total,enviados,erros,log:logDetalhado})});
  document.getElementById('btn-cancelar-disparo').textContent='← Novo disparo';
  document.getElementById('btn-cancelar-disparo').onclick=resetarDisparo;
  disparoAtivo=false;await fetch('/api/disparo/resetar',{method:'POST'});
}

async function cancelarDisparo(){await fetch('/api/disparo/cancelar',{method:'POST'});document.getElementById('prog-texto').textContent='Cancelando...';}
function resetarDisparo(){
  clientesParaDisparar=[];todosDisparoFiltrado=[];
  document.getElementById('disparo-config').style.display='block';document.getElementById('disparo-progresso').style.display='none';
  document.getElementById('btn-cancelar-disparo').textContent='✕ Cancelar disparo';document.getElementById('btn-cancelar-disparo').onclick=cancelarDisparo;
  document.getElementById('prog-log').innerHTML='';document.getElementById('d-selecionar-todos').checked=false;filtrarParaDisparo();
}

// ── IMPORTAÇÃO ────────────────────────────────────────────────────────────────
async function carregarArquivo(input){
  const file=input.files[0];if(!file)return;
  const formData=new FormData();formData.append('file',file);
  const r=await fetch('/api/preview',{method:'POST',body:formData}),d=await r.json();
  if(d.erro){toast('Erro ao ler arquivo: '+d.erro,'error');return;}
  dadosImport=d.dados;colunasImport=d.colunas;
  document.getElementById('import-step2').style.display='block';
  const abaDiv=document.getElementById('seletor-abas');
  if(d.abas&&d.abas.length>1){abaDiv.style.display='block';document.getElementById('select-aba').innerHTML=d.abas.map(a=>`<option value="${a}" ${a===d.aba_atual?'selected':''}>${a}</option>`).join('');
  document.getElementById('select-aba').onchange=async function(){const fd2=new FormData();fd2.append('file',document.getElementById('file-input').files[0]);fd2.append('aba',this.value);const r2=await fetch('/api/preview_aba',{method:'POST',body:fd2}),d2=await r2.json();if(d2.erro){toast('Erro: '+d2.erro,'error');return;}dadosImport=d2.dados;colunasImport=d2.colunas;atualizarMapaColunas(d2.colunas);atualizarPreview(d2.dados,d2.colunas);};
  }else abaDiv.style.display='none';
  atualizarMapaColunas(colunasImport);atualizarPreview(dadosImport,colunasImport);
}

const camposImport=[{key:'nome',label:'Nome'},{key:'cpf',label:'CPF'},{key:'tel1',label:'Telefone 1'},{key:'tel2',label:'Telefone 2'},{key:'convenio',label:'Convênio'},{key:'margem',label:'Margem'},{key:'dataConsulta',label:'Data consulta'},{key:'dataRetorno',label:'Data retorno'},{key:'obs',label:'Observações'}];

function atualizarMapaColunas(colunas){document.getElementById('col-map').innerHTML=camposImport.map(f=>{const auto=colunas.find(c=>c.toLowerCase().replace(/[^a-z]/g,'').includes(f.key.toLowerCase().replace(/[^a-z]/g,'')))||'';const opts=colunas.map(c=>`<option value="${c}" ${c===auto?'selected':''}>${c}</option>`).join('');return`<div class="cm-item"><label>${f.label}</label><select id="map-${f.key}"><option value="">— não importar —</option>${opts}</select></div>`;}).join('');}
function atualizarPreview(dados,colunas){document.getElementById('preview-table').innerHTML=`<thead><tr>${colunas.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${dados.slice(0,5).map(row=>`<tr>${colunas.map(c=>`<td>${row[c]||''}</td>`).join('')}</tr>`).join('')}</tbody>`;}
function cancelarImport(){document.getElementById('import-step2').style.display='none';document.getElementById('seletor-abas').style.display='none';document.getElementById('file-input').value='';}

async function importarDados(){
  const map={};camposImport.forEach(f=>{const v=document.getElementById('map-'+f.key).value;if(v)map[f.key]=v;});
  if(!map.nome){toast('Selecione a coluna de Nome!','error');return;}
  let novos=0;dadosImport.forEach(row=>{const nome=(row[map.nome]||'').toString().trim();if(!nome||nome==='nan')return;clientes.push({id:Date.now()+Math.random(),nome,cpf:map.cpf?(row[map.cpf]||'').toString().trim():'',tel1:map.tel1?(row[map.tel1]||'').toString().trim():'',tel2:map.tel2?(row[map.tel2]||'').toString().trim():'',convenio:map.convenio?(row[map.convenio]||'').toString().trim():'',margem:map.margem?(row[map.margem]||'').toString().trim():'',dataConsulta:map.dataConsulta?(row[map.dataConsulta]||'').toString().trim():'',dataRetorno:'',fechou:'nao',motivo:'',obs:map.obs?(row[map.obs]||'').toString().trim():''});novos++;});
  await salvarServidor();toast(`${novos} clientes importados!`);cancelarImport();renderDashboard();tickBadges();
  document.getElementById('sf-total').textContent=`${clientes.length} clientes`;
}

init();
</script>
</body>
</html>"""



# ── ROTAS FLASK ───────────────────────────────────────────────────────────────

@app.route('/')
@app.route('/index.html')
def index():
    return Response(HTML, mimetype='text/html; charset=utf-8')

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode      = request.args.get('hub.mode', '')
    token     = request.args.get('hub.verify_token', '')
    challenge = request.args.get('hub.challenge', '')
    if mode == 'subscribe' and token == WHATSAPP_VERIFY_TOKEN:
        print("✅ Webhook verificado!")
        return Response(challenge, mimetype='text/plain')
    return Response('Forbidden', status=403)

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    body = request.get_json(force=True, silent=True) or {}
    print(f"WEBHOOK RECEBIDO: {json.dumps(body)}")
    try:
        for entry in body.get('entry', []):
            for change in entry.get('changes', []):
                for msg in change.get('value', {}).get('messages', []):
                    remetente = msg.get('from', '')
                    texto     = msg.get('text', {}).get('body', '')
                    tipo      = msg.get('type', 'text')
                    imagem_id = None; doc_id = None; nome_doc = ''
                    if tipo == 'image':
                        imagem_id = msg.get('image', {}).get('id', '')
                        caption   = msg.get('image', {}).get('caption', '')
                        texto     = f'[IMAGEM:{imagem_id}]' + (f' {caption}' if caption else '')
                    elif tipo == 'audio': texto = '[ÁUDIO]'
                    elif tipo == 'video': texto = '[VÍDEO]'
                    elif tipo == 'document':
                        nome_doc = msg.get('document', {}).get('filename', 'documento')
                        doc_id   = msg.get('document', {}).get('id', '')
                        texto    = f'[DOCUMENTO: {nome_doc}]'
                    elif tipo == 'sticker': texto = '[FIGURINHA]'
                    elif tipo == 'interactive':
                        inter = msg.get('interactive', {})
                        itype = inter.get('type', '')
                        if itype == 'button_reply':
                            texto = inter.get('button_reply', {}).get('title', '[BOTÃO]')
                        elif itype == 'list_reply':
                            texto = inter.get('list_reply', {}).get('title', '[LISTA]')
                        else:
                            texto = '[INTERATIVO]'
                    if texto:
                        remetente = normalizar_numero(remetente)
                        msgs = carregar_mensagens(); conv = msgs['conversas']
                        if remetente not in conv:
                            nome = remetente; d = carregar_dados()
                            for c in d.get('clientes', []):
                                t = ''.join(filter(str.isdigit, c.get('tel1','')))
                                if not t.startswith('55'): t = '55'+t
                                if t == remetente: nome = c.get('nome', remetente); break
                            conv[remetente] = {'numero': remetente, 'nome': nome, 'msgs': []}
                        entrada = {'dir':'recv','texto':texto,'ts':int(time.time()*1000),'lida':False,'tipo':tipo}
                        if imagem_id: entrada['imagem_id'] = imagem_id
                        if tipo == 'document' and doc_id: entrada['doc_id'] = doc_id; entrada['doc_nome'] = nome_doc
                        conv[remetente]['msgs'].append(entrada)
                        salvar_conversa(remetente, conv[remetente])
    except Exception as e:
        print(f"Erro webhook: {e}")
    return jsonify({"ok": True})

@app.route('/api/clientes', methods=['GET'])
def api_clientes():
    return Response(json.dumps(carregar_dados(), ensure_ascii=False), mimetype='application/json')

@app.route('/api/mensagens', methods=['GET'])
def api_mensagens():
    m = carregar_mensagens()
    return Response(json.dumps(m.get('conversas', {}), ensure_ascii=False), mimetype='application/json')

@app.route('/api/disparos/historico', methods=['GET'])
def api_disparos_historico():
    return Response(json.dumps(carregar_historico_disparos(), ensure_ascii=False), mimetype='application/json')

@app.route('/api/reajustes', methods=['GET'])
def api_reajustes():
    return Response(json.dumps(carregar_reajustes(), ensure_ascii=False), mimetype='application/json')

@app.route('/api/reajustes/visualizar', methods=['POST'])
def api_reajustes_visualizar():
    body = request.get_json(force=True)
    marcar_reajuste_visto(body.get('id'))
    return jsonify({"ok": True})

@app.route('/api/imagem/<imagem_id>', methods=['GET'])
def api_imagem(imagem_id):
    try:
        req1 = urllib.request.Request(f"https://graph.facebook.com/v20.0/{imagem_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"})
        with urllib.request.urlopen(req1) as r1: info = json.loads(r1.read())
        req2 = urllib.request.Request(info.get('url',''), headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"})
        with urllib.request.urlopen(req2) as r2:
            return Response(r2.read(), mimetype=r2.headers.get('Content-Type','image/jpeg'))
    except Exception as e:
        print(f"Erro imagem: {e}"); return Response('Not found', status=404)

@app.route('/api/documento/<doc_id>', methods=['GET'])
def api_documento(doc_id):
    try:
        req1 = urllib.request.Request(f'https://graph.facebook.com/v20.0/{doc_id}',
            headers={'Authorization': f'Bearer {WHATSAPP_TOKEN}'})
        with urllib.request.urlopen(req1) as r1: info = json.loads(r1.read())
        req2 = urllib.request.Request(info.get('url',''), headers={'Authorization': f'Bearer {WHATSAPP_TOKEN}'})
        with urllib.request.urlopen(req2) as r2:
            return Response(r2.read(), mimetype=r2.headers.get('Content-Type','application/pdf'),
                headers={'Content-Disposition': 'attachment'})
    except Exception as e:
        print(f"Erro documento: {e}"); return Response('Not found', status=404)

@app.route('/api/salvar', methods=['POST'])
def api_salvar():
    body = request.get_json(force=True)
    for c in body.get('clientes', []): salvar_cliente(c)
    return jsonify({"ok": True})

@app.route('/api/excluir', methods=['POST'])
def api_excluir():
    excluir_cliente_db(request.get_json(force=True).get('id', ''))
    return jsonify({"ok": True})

@app.route('/api/importar', methods=['POST'])
def api_importar():
    body = request.get_json(force=True); novos = body.get('clientes', [])
    for c in novos: salvar_cliente(c)
    return jsonify({"ok": True, "importados": len(novos)})

@app.route('/api/disparos/salvar', methods=['POST'])
def api_disparos_salvar():
    body = request.get_json(force=True)
    salvar_disparo(body.get('template',''), body.get('total',0), body.get('enviados',0), body.get('erros',0), body.get('log',[]))
    return jsonify({"ok": True})

@app.route('/api/disparo/enviar', methods=['POST'])
def api_disparo_enviar():
    body = request.get_json(force=True)
    resultado = enviar_template(body.get('telefone',''), body.get('template',''), body.get('nome',''))
    return Response(json.dumps(resultado, ensure_ascii=False), mimetype='application/json')

@app.route('/api/disparo/cancelar', methods=['POST'])
def api_disparo_cancelar():
    disparo_status['cancelar'] = True; return jsonify({"ok": True})

@app.route('/api/disparo/status', methods=['GET'])
def api_disparo_status():
    return Response(json.dumps(disparo_status), mimetype='application/json')

@app.route('/api/disparo/resetar', methods=['POST'])
def api_disparo_resetar():
    disparo_status.update({"ativo":False,"cancelar":False,"total":0,"enviados":0,"erros":0,"log":[]})
    return jsonify({"ok": True})

@app.route('/api/whatsapp', methods=['POST'])
def api_whatsapp():
    body = request.get_json(force=True)
    telefone = body.get('telefone',''); mensagem = body.get('mensagem',''); salvar = body.get('salvar', False)
    resultado = enviar_whatsapp(telefone, mensagem)
    if salvar and (resultado.get('messages') or resultado.get('ok')):
        numero = ''.join(filter(str.isdigit, telefone))
        if not numero.startswith('55'): numero = '55' + numero
        msgs = carregar_mensagens(); conv = msgs['conversas']
        if numero not in conv: conv[numero] = {'numero':numero,'nome':numero,'msgs':[]}
        conv[numero]['msgs'].append({'dir':'sent','texto':mensagem,'ts':int(time.time()*1000),'lida':True})
        salvar_conversa(numero, conv[numero])
    return Response(json.dumps(resultado, ensure_ascii=False), mimetype='application/json')

@app.route('/api/mensagens/lidas', methods=['POST'])
def api_mensagens_lidas():
    body = request.get_json(force=True); numero = body.get('numero','')
    msgs = carregar_mensagens()
    if numero in msgs.get('conversas', {}):
        for m in msgs['conversas'][numero].get('msgs', []): m['lida'] = True
        salvar_conversa(numero, msgs['conversas'][numero])
    return jsonify({"ok": True})

@app.route('/api/preview', methods=['POST'])
@app.route('/api/preview_aba', methods=['POST'])
def api_preview():
    import io
    aba = request.form.get('aba', ''); file_data = None
    if 'file' in request.files: file_data = request.files['file'].read()
    if request.path == '/api/preview_aba' and aba and file_data:
        try:
            xl = pd.ExcelFile(io.BytesIO(file_data)); df = xl.parse(aba).fillna('')
            return Response(json.dumps({'colunas':list(df.columns),'dados':df.to_dict(orient='records')}, ensure_ascii=False, default=str), mimetype='application/json')
        except Exception as e:
            return Response(json.dumps({'erro': str(e)}), mimetype='application/json')
    try:
        filename = request.files['file'].filename if 'file' in request.files else ''
        if filename.lower().endswith('.csv'):
            try: df = pd.read_csv(io.BytesIO(file_data), encoding='utf-8', on_bad_lines='skip')
            except: df = pd.read_csv(io.BytesIO(file_data), encoding='latin-1', on_bad_lines='skip')
            df = df.fillna('')
            resp = json.dumps({'colunas':list(df.columns),'dados':df.to_dict(orient='records'),'abas':[],'aba_atual':''}, ensure_ascii=False, default=str)
        else:
            xl = pd.ExcelFile(io.BytesIO(file_data)); abas = xl.sheet_names; aba_atual = abas[0]
            df = xl.parse(aba_atual).fillna('')
            resp = json.dumps({'colunas':list(df.columns),'dados':df.to_dict(orient='records'),'abas':abas,'aba_atual':aba_atual}, ensure_ascii=False, default=str)
    except Exception as e:
        resp = json.dumps({'erro': str(e)})
    return Response(resp, mimetype='application/json')


if __name__ == '__main__':
    print(f"🚀 CRM Consignado iniciando na porta {PORT}")
    app.run(host='0.0.0.0', port=PORT)
