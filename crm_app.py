"""
CRM - Sistema de Gestão de Clientes
=====================================
Como usar:
1. Abra o CMD e rode: py crm_app.py
2. O sistema abre automaticamente no navegador
3. Use normalmente!
"""

import json
import os
import webbrowser
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import pandas as pd

PORT = int(os.environ.get('PORT', 8765))
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm_dados.json")
MSG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm_mensagens.json")

# ── Configuração WhatsApp ──────────────────────────────────────────────────────
WHATSAPP_VERIFY_TOKEN = "Meucrm26"
WHATSAPP_TOKEN        = "EAAVXA6vwBM4BRiTlfKFBBYbUPcNSomsaLZALG8PO3RI7TxshlJSCZCTmlENGUSWfopuPEL0zV5uj3tLMQdnw23r8b036t3k1iayPOv2Hs3NwWNt1a8TZC1rpeVIc8TvrpFqegAgZBD61gUsAVO1ZCe9Q6NMsEbkatzKTYdp4IyALoXTfi921ZA5TFMucIohgZDZD"
WHATSAPP_PHONE_ID     = "1166793639847817"
# ──────────────────────────────────────────────────────────────────────────────

def carregar_dados():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"clientes": []}

def salvar_dados(dados):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def carregar_mensagens():
    if os.path.exists(MSG_FILE):
        try:
            with open(MSG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"conversas": {}}

def salvar_mensagens(msgs):
    with open(MSG_FILE, 'w', encoding='utf-8') as f:
        json.dump(msgs, f, ensure_ascii=False, indent=2)

def enviar_whatsapp(telefone, mensagem):
    import urllib.request
    numero = ''.join(filter(str.isdigit, telefone))
    if numero.startswith('0'):
        numero = numero[1:]
    if not numero.startswith('55'):
        numero = '55' + numero
    print(f"📤 Enviando WhatsApp para: {numero} | Mensagem: {mensagem[:40]}...")
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensagem}
    }).encode('utf-8')
    req = urllib.request.Request(
        f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages",
        data=payload,
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        erro = e.read().decode('utf-8')
        print(f"❌ Erro WhatsApp: {erro}")
        return {"erro": erro}
    except Exception as e:
        return {"erro": str(e)}

dados_globais = carregar_dados()
mensagens_globais = carregar_mensagens()

HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CRM Clientes</title>
<style>

*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#F5F4F0;--surface:#fff;--border:#E2E0D8;--text:#1A1A18;--muted:#7A7A74;--green:#1D6A4A;--green-bg:#E8F5EE;--red:#A32D2D;--red-bg:#FCEBEB;--amber:#854F0B;--amber-bg:#FAEEDA;--blue:#185FA5;--blue-bg:#E6F1FB}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);font-size:14px}
.layout{display:flex;min-height:100vh}
.sidebar{width:220px;background:var(--text);color:#fff;display:flex;flex-direction:column;padding:24px 0;position:fixed;height:100vh;z-index:10}
.logo{padding:0 20px 24px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:16px}
.logo-title{font-size:16px;font-weight:600;letter-spacing:-.3px}
.logo-sub{font-size:11px;color:rgba(255,255,255,.45);margin-top:2px;font-family:'Courier New',monospace}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;cursor:pointer;color:rgba(255,255,255,.55);font-size:13px;font-weight:500;transition:all .15s;border-left:2px solid transparent;border:none;background:none;width:100%;text-align:left;font-family:'DM Sans',sans-serif}
.nav-item:hover{color:#fff;background:rgba(255,255,255,.06)}
.nav-item.active{color:#fff;background:rgba(255,255,255,.1);border-left:2px solid #fff}
.nav-badge{margin-left:auto;background:var(--red);color:#fff;font-size:10px;padding:1px 6px;border-radius:10px;font-family:'Courier New',monospace}
.main{margin-left:220px;flex:1;padding:32px}
.page{display:none}.page.active{display:block}
.page-title{font-size:22px;font-weight:600;letter-spacing:-.5px;margin-bottom:24px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}
.metric-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px}
.metric-label{font-size:11px;color:var(--muted);font-weight:500;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
.metric-value{font-size:28px;font-weight:600;letter-spacing:-1px;font-family:'Courier New',monospace}
.metric-value.green{color:var(--green)}.metric-value.amber{color:var(--amber)}.metric-value.red{color:var(--red)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:16px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}
.form-group{display:flex;flex-direction:column;gap:5px}
.form-group.full{grid-column:1/-1}
.form-group label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
input,select,textarea{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:9px 12px;font-size:13px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--text);outline:none;transition:border .15s;width:100%}
input:focus,select:focus,textarea:focus{border-color:var(--text)}
textarea{resize:vertical;min-height:80px}
.btn-primary{background:var(--text);color:#fff;border:none;padding:10px 22px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif}
.btn-ghost{background:none;border:1px solid var(--border);padding:9px 18px;border-radius:8px;font-size:13px;cursor:pointer;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--text)}
.btn-danger{background:none;border:1px solid var(--border);padding:6px 12px;border-radius:6px;font-size:12px;cursor:pointer;color:var(--red);font-family:'DM Sans',sans-serif}
.btn-edit{background:none;border:1px solid var(--border);padding:6px 12px;border-radius:6px;font-size:12px;cursor:pointer;color:var(--text);font-family:'DM Sans',sans-serif}
.btn-row{display:flex;gap:10px;align-items:center}
.success-msg{color:var(--green);font-size:12px;display:none}
.search-row{display:flex;gap:10px;margin-bottom:16px}
.search-row input{flex:1}
.search-row select{width:160px}
.client-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin-bottom:10px}
.client-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
.client-name{font-size:15px;font-weight:600}
.client-badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{font-size:11px;padding:3px 10px;border-radius:20px;font-weight:600}
.badge-sim{background:var(--green-bg);color:var(--green)}
.badge-nao{background:var(--bg);color:var(--muted);border:1px solid var(--border)}
.badge-carteira{background:var(--blue-bg);color:var(--blue)}
.badge-hoje{background:var(--red-bg);color:var(--red)}
.badge-alerta{background:var(--amber-bg);color:var(--amber)}
.client-info{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}
.client-info-item{font-size:12px;color:var(--muted)}
.client-info-item strong{color:var(--text);font-weight:500}
.client-obs{font-size:12px;color:var(--muted);background:var(--bg);padding:8px 12px;border-radius:6px;margin-bottom:10px}
.client-actions{display:flex;gap:8px}
.retorno-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 20px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.retorno-left{flex:1}
.retorno-nome{font-size:14px;font-weight:600;margin-bottom:4px}
.retorno-detalhe{font-size:12px;color:var(--muted)}
.retorno-right{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.retorno-data{font-size:11px;color:var(--muted);font-family:'Courier New',monospace}
.empty-state{text-align:center;padding:48px;color:var(--muted)}
.section-title{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.import-area{border:2px dashed var(--border);border-radius:12px;padding:32px;text-align:center;margin-bottom:20px;cursor:pointer;transition:border-color .2s}
.import-area:hover{border-color:var(--text)}
.import-area input{display:none}
.col-map{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px}
.col-map-item{display:flex;flex-direction:column;gap:5px}
.col-map-item label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.preview-table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:16px}
.preview-table th{background:var(--bg);padding:8px 12px;text-align:left;font-weight:600;border-bottom:1px solid var(--border)}
.preview-table td{padding:8px 12px;border-bottom:1px solid var(--border)}
.btn-whatsapp{background:#25D366;border:none;padding:6px 12px;border-radius:6px;font-size:12px;cursor:pointer;color:#fff;font-family:'DM Sans',sans-serif;font-weight:600}
.chat-list{display:flex;flex-direction:column;gap:8px}
.chat-item{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 18px;cursor:pointer;transition:border-color .15s}
.chat-item:hover{border-color:var(--text)}
.chat-item.unread{border-left:3px solid var(--green)}
.chat-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.chat-name{font-weight:600;font-size:14px}
.chat-time{font-size:11px;color:var(--muted);font-family:'Courier New',monospace}
.chat-preview{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-unread-badge{background:var(--green);color:#fff;font-size:10px;padding:1px 6px;border-radius:10px;margin-left:8px}
.msg-window{background:var(--surface);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;height:calc(100vh - 120px)}
.msg-header{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
.msg-back{cursor:pointer;font-size:18px;background:none;border:none;color:var(--text)}
.msg-contact{font-weight:600;font-size:15px}
.msg-contact-num{font-size:11px;color:var(--muted);font-family:'Courier New',monospace}
.msg-body{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:8px;background:#f0f2f5}
.msg-bubble{max-width:70%;padding:8px 14px;border-radius:12px;font-size:13px;line-height:1.5}
.msg-bubble.received{background:#fff;border-radius:0 12px 12px 12px;align-self:flex-start}
.msg-bubble.sent{background:#dcf8c6;border-radius:12px 0 12px 12px;align-self:flex-end}
.msg-time{font-size:10px;color:var(--muted);margin-top:3px;text-align:right;font-family:'Courier New',monospace}
.msg-footer{padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px}
.msg-footer input{flex:1}
.tag{display:inline-block;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:2px 8px;font-size:11px;font-family:'Courier New',monospace;color:var(--muted)}
</style>
</head>
<body>
<div class="layout">
<nav class="sidebar">
  <div class="logo">
    <div class="logo-title">CRM Clientes</div>
    <div class="logo-sub">Gestão de carteira</div>
  </div>
  <button class="nav-item active" onclick="showPage('dashboard',this)">📊 Início</button>
  <button class="nav-item" onclick="showPage('novo',this)">➕ Novo cliente</button>
  <button class="nav-item" onclick="showPage('lista',this)">👥 Clientes</button>
  <button class="nav-item" onclick="showPage('retornos',this)" id="nav-retornos">🔔 Retornos <span class="nav-badge" id="badge-retorno" style="display:none">0</span></button>
  <button class="nav-item" onclick="showPage('mensagens',this)" id="nav-mensagens">💬 Mensagens <span class="nav-badge" id="badge-msg" style="display:none">0</span></button>
  <button class="nav-item" onclick="showPage('importar',this)">📥 Importar planilha</button>
</nav>

<main class="main">

<div id="page-dashboard" class="page active">
  <div class="page-title">Início</div>
  <div class="metrics">
    <div class="metric-card"><div class="metric-label">Total clientes</div><div class="metric-value" id="m-total">0</div></div>
    <div class="metric-card"><div class="metric-label">Fecharam</div><div class="metric-value green" id="m-fechou">0</div></div>
    <div class="metric-card"><div class="metric-label">Em negociação</div><div class="metric-value amber" id="m-negoc">0</div></div>
    <div class="metric-card"><div class="metric-label">Retornos urgentes</div><div class="metric-value red" id="m-urgentes">0</div></div>
  </div>
  <div class="section-title">Retornos urgentes</div>
  <div id="dash-retornos"></div>
</div>

<div id="page-novo" class="page">
  <div class="page-title" id="form-title">Novo cliente</div>
  <div class="card">
    <div class="form-grid">
      <div class="form-group"><label>Nome completo *</label><input type="text" id="f-nome" placeholder="Nome do cliente"></div>
      <div class="form-group"><label>CPF</label><input type="text" id="f-cpf" placeholder="000.000.000-00"></div>
      <div class="form-group"><label>Telefone 1</label><input type="text" id="f-tel1" placeholder="(00) 00000-0000"></div>
      <div class="form-group"><label>Telefone 2</label><input type="text" id="f-tel2" placeholder="(00) 00000-0000"></div>
      <div class="form-group"><label>Convênio</label>
        <select id="f-convenio" onchange="togglePrefeitura()"><option value="">Selecione...</option><option>Prefeitura</option><option>INSS</option><option>Governo Estadual</option><option>Forças Armadas</option><option>Privado</option><option>Outro</option></select>
      </div>
      <div class="form-group" id="grupo-prefeitura" style="display:none"><label>Qual prefeitura?</label><input type="text" id="f-prefeitura" placeholder="Ex: Prefeitura de Foz do Iguaçu"></div>
      <div class="form-group"><label>Margem disponível (R$)</label><input type="text" id="f-margem" placeholder="0,00"></div>
      <div class="form-group"><label>Data da consulta</label><input type="date" id="f-data-consulta"></div>
      <div class="form-group"><label>Data de retorno</label><input type="date" id="f-data-retorno"></div>
      <div class="form-group"><label>Status</label>
        <select id="f-fechou"><option value="nao">Em negociação</option><option value="sim">Fechou</option><option value="carteira">Carteira</option></select>
      </div>
      <div class="form-group"><label>Motivo do retorno</label>
        <select id="f-motivo"><option value="">Selecione...</option><option>Abertura de margem</option><option>Refinanciamento</option><option>Portabilidade</option><option>Novo produto</option><option>Follow-up</option><option>Outro</option></select>
      </div>
      <div class="form-group full"><label>Observações</label><textarea id="f-obs" placeholder="Anotações sobre o cliente..."></textarea></div>
    </div>
    <div class="btn-row">
      <button class="btn-primary" onclick="salvarCliente()">Salvar cliente</button>
      <button class="btn-ghost" onclick="limparForm()">Limpar</button>
      <span class="success-msg" id="msg-salvo">✓ Salvo!</span>
    </div>
  </div>
</div>

<div id="page-lista" class="page">
  <div class="page-title">Clientes</div>
  <div class="search-row">
    <input type="text" id="busca" placeholder="Buscar por nome, CPF ou convênio..." oninput="renderLista()">
    <select onchange="renderLista()" id="filtro-status">
      <option value="">Todos</option><option value="sim">Fecharam</option><option value="nao">Em negociação</option><option value="carteira">Carteira</option>
    </select>
  </div>
  <div id="lista-clientes"></div>
</div>

<div id="page-retornos" class="page">
  <div class="page-title">Retornos agendados</div>
  <div id="lista-retornos"></div>
</div>

<div id="page-mensagens" class="page">
  <div id="msg-lista-view">
    <div class="page-title">💬 Mensagens</div>
    <div id="msg-lista" class="chat-list"><div class="empty-state">Nenhuma mensagem recebida ainda.</div></div>
  </div>
  <div id="msg-chat-view" style="display:none">
    <div class="msg-window">
      <div class="msg-header">
        <button class="msg-back" onclick="voltarLista()">←</button>
        <div>
          <div class="msg-contact" id="chat-nome"></div>
          <div class="msg-contact-num" id="chat-num"></div>
        </div>
      </div>
      <div class="msg-body" id="chat-msgs"></div>
      <div class="msg-footer">
        <input type="text" id="chat-input" placeholder="Digite uma mensagem..." onkeydown="if(event.key==='Enter')enviarResposta()">
        <button class="btn-primary" onclick="enviarResposta()">Enviar</button>
      </div>
    </div>
  </div>
</div>

<div id="page-importar" class="page">
  <div class="page-title">Importar planilha</div>
  <div class="card">
    <p style="color:var(--muted);font-size:13px;margin-bottom:16px">Selecione um arquivo Excel (.xlsx) e mapeie as colunas para os campos do CRM.</p>
    <div class="import-area" onclick="document.getElementById('file-input').click()">
      <input type="file" id="file-input" accept=".xlsx,.xls,.csv" onchange="carregarArquivo(this)">
      <div style="font-size:32px;margin-bottom:8px">📂</div>
      <div style="font-weight:600;margin-bottom:4px">Clique para selecionar o arquivo</div>
      <div style="font-size:12px;color:var(--muted)">Aceita .xlsx, .xls, .csv</div>
    </div>
    <div id="seletor-abas" style="display:none;background:var(--amber-bg);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:16px">
      <div style="font-size:12px;font-weight:600;color:var(--amber);margin-bottom:8px">📋 Planilha com múltiplas abas detectada!</div>
      <span style="font-size:12px;color:var(--amber-bg)"></span>
      <div style="display:flex;align-items:center;gap:10px;margin-top:8px">
        <label style="font-size:12px;font-weight:600;color:var(--muted)">Selecionar aba:</label>
        <select id="select-aba" style="width:200px;font-size:13px"></select>
      </div>
    </div>
    <div id="import-step2" style="display:none">
      <div class="section-title" style="margin-bottom:16px">Mapeie as colunas</div>
      <p style="font-size:12px;color:var(--muted);margin-bottom:16px">Selecione qual coluna da sua planilha corresponde a cada campo. Deixe em branco se não tiver.</p>
      <div class="col-map" id="col-map"></div>
      <div style="margin-bottom:16px">
        <div class="section-title">Prévia (5 primeiros registros)</div>
        <div style="overflow-x:auto"><table class="preview-table" id="preview-table"></table></div>
      </div>
      <div class="btn-row">
        <button class="btn-primary" onclick="importarDados()">📥 Importar</button>
        <button class="btn-ghost" onclick="cancelarImport()">Cancelar</button>
        <span class="success-msg" id="msg-import">✓ Importado com sucesso!</span>
      </div>
    </div>
  </div>
</div>

</main>
</div>

<script>
let clientes = [];
let editId = null;
let dadosImport = [];
let colunasImport = [];

// Carrega dados do servidor
async function init() {
  const r = await fetch('/api/clientes');
  const d = await r.json();
  clientes = d.clientes || [];
  renderDashboard();
  atualizarBadge();
  carregarMensagens();
  setInterval(atualizarBadge, 60000);
  document.getElementById('f-data-consulta').value = hoje();
}

async function salvarServidor() {
  await fetch('/api/salvar', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({clientes})
  });
}

function hoje() { return new Date().toISOString().split('T')[0]; }

function diasAte(data) {
  if (!data) return null;
  const d = new Date(data + 'T00:00:00');
  const t = new Date(hoje() + 'T00:00:00');
  return Math.round((d - t) / 86400000);
}

function showPage(name, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  if (el) el.classList.add('active');
  if (name === 'lista') renderLista();
  if (name === 'retornos') renderRetornos();
  if (name === 'dashboard') renderDashboard();
}

function togglePrefeitura() {
  const v = document.getElementById('f-convenio').value;
  document.getElementById('grupo-prefeitura').style.display = v === 'Prefeitura' ? 'flex' : 'none';
}

function salvarCliente() {
  const nome = document.getElementById('f-nome').value.trim();
  if (!nome) { alert('Informe o nome do cliente.'); return; }
  const c = {
    id: editId || Date.now(),
    nome, cpf: document.getElementById('f-cpf').value,
    tel1: document.getElementById('f-tel1').value, tel2: document.getElementById('f-tel2').value,
    convenio: document.getElementById('f-convenio').value,
    prefeitura: document.getElementById('f-prefeitura').value,
    margem: document.getElementById('f-margem').value,
    dataConsulta: document.getElementById('f-data-consulta').value,
    dataRetorno: document.getElementById('f-data-retorno').value,
    fechou: document.getElementById('f-fechou').value,
    motivo: document.getElementById('f-motivo').value, obs: document.getElementById('f-obs').value
  };
  if (editId) { const i = clientes.findIndex(x => x.id === editId); if (i>=0) clientes[i]=c; editId=null; document.getElementById('form-title').textContent='Novo cliente'; }
  else clientes.push(c);
  salvarServidor();
  limparForm();
  const m = document.getElementById('msg-salvo'); m.style.display='inline'; setTimeout(()=>m.style.display='none',3000);
  atualizarBadge(); renderDashboard();
}

function limparForm() {
  ['f-nome','f-cpf','f-tel1','f-tel2','f-margem','f-obs','f-prefeitura'].forEach(id=>document.getElementById(id).value='');
  ['f-convenio','f-fechou','f-motivo'].forEach(id=>document.getElementById(id).selectedIndex=0);
  document.getElementById('f-data-consulta').value=hoje();
  document.getElementById('f-data-retorno').value=''; editId=null;
  document.getElementById('form-title').textContent='Novo cliente';
}

function editarCliente(id) {
  const c = clientes.find(x=>x.id===id); if (!c) return;
  editId=id;
  document.getElementById('f-nome').value=c.nome;
  document.getElementById('f-cpf').value=c.cpf||'';
  document.getElementById('f-tel1').value=c.tel1||'';
  document.getElementById('f-tel2').value=c.tel2||'';
  document.getElementById('f-convenio').value=c.convenio||''; document.getElementById('f-prefeitura').value=c.prefeitura||''; togglePrefeitura();
  document.getElementById('f-margem').value=c.margem||'';
  document.getElementById('f-data-consulta').value=c.dataConsulta||'';
  document.getElementById('f-data-retorno').value=c.dataRetorno||'';
  document.getElementById('f-fechou').value=c.fechou||'nao';
  document.getElementById('f-motivo').value=c.motivo||'';
  document.getElementById('f-obs').value=c.obs||'';
  document.getElementById('form-title').textContent='Editar cliente';
  showPage('novo', document.querySelectorAll('.nav-item')[1]);
}

function excluirCliente(id) {
  if (!confirm('Excluir este cliente?')) return;
  clientes=clientes.filter(x=>x.id!==id); salvarServidor(); renderLista(); renderDashboard(); atualizarBadge();
}

function renderLista() {
  const busca=(document.getElementById('busca').value||'').toLowerCase();
  const filtro=document.getElementById('filtro-status').value;
  let lista=clientes.filter(c=>{
    const m=!busca||c.nome.toLowerCase().includes(busca)||(c.cpf||'').includes(busca)||(c.convenio||'').toLowerCase().includes(busca);
    return m&&(!filtro||c.fechou===filtro);
  });
  const el=document.getElementById('lista-clientes');
  if (!lista.length){el.innerHTML='<div class="empty-state"><p>Nenhum cliente encontrado</p></div>';return;}
  el.innerHTML=lista.map(c=>{
    const dias=diasAte(c.dataRetorno);
    let rb='';
    if(dias!==null){if(dias<0)rb=`<span class="badge badge-alerta">Atrasado ${Math.abs(dias)}d</span>`;else if(dias===0)rb=`<span class="badge badge-hoje">Retorno hoje!</span>`;else if(dias<=7)rb=`<span class="badge badge-alerta">Retorno em ${dias}d</span>`;}
    const sb=c.fechou==='sim'?'badge-sim':c.fechou==='carteira'?'badge-carteira':'badge-nao';
    const sl=c.fechou==='sim'?'Fechou':c.fechou==='carteira'?'Carteira':'Em negociação';
    return `<div class="client-card">
      <div class="client-header"><div class="client-name">${c.nome}</div><div class="client-badges"><span class="badge ${sb}">${sl}</span>${rb}</div></div>
      <div class="client-info">
        <div class="client-info-item">CPF: <strong>${c.cpf||'—'}</strong></div>
        <div class="client-info-item">Tel: <strong>${c.tel1||'—'}</strong></div>
        <div class="client-info-item">Convênio: <strong>${c.convenio||(c.prefeitura?'Prefeitura':'—')}${c.prefeitura?' - '+c.prefeitura:''}</strong></div>
        <div class="client-info-item">Margem: <strong>R$ ${c.margem||'—'}</strong></div>
        <div class="client-info-item">Consulta: <strong>${c.dataConsulta||'—'}</strong></div>
        <div class="client-info-item">Retorno: <strong>${c.dataRetorno||'—'}</strong></div>
      </div>
      ${c.obs?`<div class="client-obs">${c.obs}</div>`:''}
      <div class="client-actions"><button class="btn-edit" onclick="editarCliente(${c.id})">✏ Editar</button><button class="btn-danger" onclick="excluirCliente(${c.id})">✕ Excluir</button>${c.tel1?`<button class="btn-whatsapp" onclick="abrirChat('${c.tel1}','${c.nome}')">💬 WhatsApp</button>`:''}</div>
    </div>`;
  }).join('');
}

function renderRetornos() {
  const lista=clientes.filter(c=>c.dataRetorno).sort((a,b)=>a.dataRetorno.localeCompare(b.dataRetorno));
  const el=document.getElementById('lista-retornos');
  if(!lista.length){el.innerHTML='<div class="empty-state"><p>Nenhum retorno agendado</p></div>';return;}
  el.innerHTML=lista.map(c=>{
    const dias=diasAte(c.dataRetorno);
    const badge=dias<0?`<span class="badge badge-alerta">Atrasado ${Math.abs(dias)}d</span>`:dias===0?`<span class="badge badge-hoje">Hoje!</span>`:dias<=7?`<span class="badge badge-alerta">Em ${dias}d</span>`:`<span class="badge badge-nao">Em ${dias}d</span>`;
    return `<div class="retorno-card">
      <div class="retorno-left"><div class="retorno-nome">${c.nome}</div><div class="retorno-detalhe">${c.tel1||'—'} · ${c.convenio||'—'} · ${c.motivo||'Retorno agendado'}</div>${c.obs?`<div class="retorno-detalhe">${c.obs}</div>`:''}</div>
      <div class="retorno-right"><div class="retorno-data">${c.dataRetorno}</div>${badge}<button class="btn-edit" onclick="editarCliente(${c.id})">✏ Editar</button></div>
    </div>`;
  }).join('');
}

function renderDashboard() {
  document.getElementById('m-total').textContent=clientes.length;
  document.getElementById('m-fechou').textContent=clientes.filter(c=>c.fechou==='sim').length;
  document.getElementById('m-negoc').textContent=clientes.filter(c=>c.fechou==='nao').length;
  const urgentes=clientes.filter(c=>{const d=diasAte(c.dataRetorno);return d!==null&&d<=3;});
  document.getElementById('m-urgentes').textContent=urgentes.length;
  const el=document.getElementById('dash-retornos');
  if(!urgentes.length){el.innerHTML='<div class="empty-state" style="padding:32px"><p>Nenhum retorno urgente. Tudo em dia! ✓</p></div>';return;}
  el.innerHTML=urgentes.sort((a,b)=>a.dataRetorno.localeCompare(b.dataRetorno)).map(c=>{
    const dias=diasAte(c.dataRetorno);
    const badge=dias<0?`<span class="badge badge-alerta">Atrasado ${Math.abs(dias)}d</span>`:dias===0?`<span class="badge badge-hoje">Hoje!</span>`:`<span class="badge badge-alerta">Em ${dias}d</span>`;
    return `<div class="retorno-card"><div class="retorno-left"><div class="retorno-nome">${c.nome}</div><div class="retorno-detalhe">${c.tel1||'—'} · ${c.motivo||c.convenio||'—'}</div></div><div class="retorno-right"><div class="retorno-data">${c.dataRetorno}</div>${badge}<button class="btn-edit" onclick="editarCliente(${c.id})">✏</button></div></div>`;
  }).join('');
}

function atualizarBadge() {
  const n=clientes.filter(c=>{const d=diasAte(c.dataRetorno);return d!==null&&d<=0;}).length;
  const b=document.getElementById('badge-retorno'); b.textContent=n; b.style.display=n>0?'inline':'none';
}

// IMPORTAÇÃO
async function carregarArquivo(input) {
  const file = input.files[0]; if (!file) return;
  const formData = new FormData(); formData.append('file', file);
  const r = await fetch('/api/preview', {method:'POST', body: formData});
  const d = await r.json();
  if (d.erro) { alert('Erro ao ler arquivo: ' + d.erro); return; }
  dadosImport = d.dados; colunasImport = d.colunas;
  document.getElementById('import-step2').style.display = 'block';
  // Mostra seletor de abas se houver mais de uma
  const abaDiv = document.getElementById('seletor-abas');
  if (d.abas && d.abas.length > 1) {
    abaDiv.style.display = 'block';
    document.getElementById('select-aba').innerHTML = d.abas.map(a => `<option value="${a}" ${a===d.aba_atual?'selected':''}>${a}</option>`).join('');
    abaDiv.querySelector('span').textContent = `Aba: ${d.aba_atual} (${d.dados.length} registros)`;
    document.getElementById('select-aba').onchange = async function() {
      const novaAba = this.value;
      const fd2 = new FormData();
      fd2.append('file', document.getElementById('file-input').files[0]);
      fd2.append('aba', novaAba);
      const r2 = await fetch('/api/preview_aba', {method:'POST', body: fd2});
      const d2 = await r2.json();
      if (d2.erro) { alert('Erro: ' + d2.erro); return; }
      dadosImport = d2.dados; colunasImport = d2.colunas;
      abaDiv.querySelector('span').textContent = `Aba: ${novaAba} (${d2.dados.length} registros)`;
      atualizarMapaColunas(d2.colunas);
      atualizarPreview(d2.dados, d2.colunas);
    };
  } else {
    abaDiv.style.display = 'none';
  }
  const campos = [
    {key:'nome', label:'Nome'},
    {key:'cpf', label:'CPF'},
    {key:'tel1', label:'Telefone 1'},
    {key:'tel2', label:'Telefone 2'},
    {key:'convenio', label:'Convênio'},
    {key:'margem', label:'Margem'},
    {key:'dataConsulta', label:'Data consulta'},
    {key:'dataRetorno', label:'Data retorno'},
    {key:'obs', label:'Observações'}
  ];
  const opcs = '<option value="">— não importar —</option>' + colunasImport.map(c=>`<option value="${c}">${c}</option>`).join('');
  document.getElementById('col-map').innerHTML = campos.map(f=>{
    const auto = colunasImport.find(c => c.toLowerCase().replace(/[^a-z]/g,'').includes(f.key.toLowerCase().replace(/[^a-z]/g,''))) || '';
    const opts = colunasImport.map(c=>`<option value="${c}" ${c===auto?'selected':''}>${c}</option>`).join('');
    return `<div class="col-map-item"><label>${f.label}</label><select id="map-${f.key}"><option value="">— não importar —</option>${opts}</select></div>`;
  }).join('');
  const preview = dadosImport.slice(0,5);
  document.getElementById('preview-table').innerHTML = `<thead><tr>${colunasImport.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${preview.map(row=>`<tr>${colunasImport.map(c=>`<td>${row[c]||''}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

function atualizarMapaColunas(colunas) {
  const campos = [
    {key:'nome',label:'Nome'},{key:'cpf',label:'CPF'},{key:'tel1',label:'Telefone 1'},
    {key:'tel2',label:'Telefone 2'},{key:'convenio',label:'Convênio'},{key:'margem',label:'Margem'},
    {key:'dataConsulta',label:'Data consulta'},{key:'dataRetorno',label:'Data retorno'},{key:'obs',label:'Observações'}
  ];
  document.getElementById('col-map').innerHTML = campos.map(f=>{
    const auto = colunas.find(c => c.toLowerCase().replace(/[^a-z]/g,'').includes(f.key.toLowerCase().replace(/[^a-z]/g,''))) || '';
    const opts = colunas.map(c=>`<option value="${c}" ${c===auto?'selected':''}>${c}</option>`).join('');
    return `<div class="col-map-item"><label>${f.label}</label><select id="map-${f.key}"><option value="">— não importar —</option>${opts}</select></div>`;
  }).join('');
}

function atualizarPreview(dados, colunas) {
  const preview = dados.slice(0,5);
  document.getElementById('preview-table').innerHTML = `<thead><tr>${colunas.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${preview.map(row=>`<tr>${colunas.map(c=>`<td>${row[c]||''}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

function cancelarImport() { document.getElementById('import-step2').style.display='none'; document.getElementById('file-input').value=''; }

async function importarDados() {
  const map = {};
  ['nome','cpf','tel1','tel2','convenio','margem','dataConsulta','dataRetorno','obs'].forEach(k=>{
    const v = document.getElementById('map-'+k).value; if (v) map[k]=v;
  });
  if (!map.nome) { alert('Selecione pelo menos a coluna de Nome!'); return; }
  let novos = 0;
  dadosImport.forEach(row => {
    const nome = (row[map.nome]||'').toString().trim(); if (!nome || nome==='nan') return;
    const c = {
      id: Date.now() + Math.random(),
      nome, cpf: map.cpf?(row[map.cpf]||'').toString().trim():'',
      tel1: map.tel1?(row[map.tel1]||'').toString().trim():'',
      tel2: map.tel2?(row[map.tel2]||'').toString().trim():'',
      convenio: map.convenio?(row[map.convenio]||'').toString().trim():'',
      margem: map.margem?(row[map.margem]||'').toString().trim():'',
      dataConsulta: map.dataConsulta?(row[map.dataConsulta]||'').toString().trim():'',
      dataRetorno: '', fechou: 'nao', motivo: '',
      obs: map.obs?(row[map.obs]||'').toString().trim():''
    };
    clientes.push(c); novos++;
  });
  await salvarServidor();
  const m=document.getElementById('msg-import'); m.textContent=`✓ ${novos} clientes importados!`; m.style.display='inline';
  setTimeout(()=>m.style.display='none',4000);
  renderDashboard(); atualizarBadge();
}

// ── Mensagens WhatsApp ────────────────────────────────────────────────────────
let conversas = {};
let chatAtual = null;

async function carregarMensagens() {
  try {
    const r = await fetch('/api/mensagens');
    conversas = await r.json();
    renderListaMensagens();
    atualizarBadgeMsg();
  } catch(e) {}
}

function atualizarBadgeMsg() {
  let naoLidas = 0;
  Object.values(conversas).forEach(c => {
    naoLidas += (c.msgs||[]).filter(m => m.dir==='recv' && !m.lida).length;
  });
  const b = document.getElementById('badge-msg');
  if (naoLidas > 0) { b.textContent = naoLidas; b.style.display='inline'; }
  else { b.style.display='none'; }
}

function renderListaMensagens() {
  const el = document.getElementById('msg-lista');
  const lista = Object.values(conversas).sort((a,b) => {
    const ua = a.msgs?.slice(-1)[0]?.ts||0;
    const ub = b.msgs?.slice(-1)[0]?.ts||0;
    return ub - ua;
  });
  if (!lista.length) { el.innerHTML='<div class="empty-state">Nenhuma mensagem recebida ainda.</div>'; return; }
  el.innerHTML = lista.map(c => {
    const ultima = c.msgs?.slice(-1)[0];
    const naoLidas = (c.msgs||[]).filter(m => m.dir==='recv' && !m.lida).length;
    const hora = ultima ? new Date(ultima.ts).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}) : '';
    return `<div class="chat-item ${naoLidas?'unread':''}" onclick="abrirChat('${c.numero}','${c.nome||c.numero}')">
      <div class="chat-header">
        <span class="chat-name">${c.nome||c.numero} ${naoLidas?`<span class="chat-unread-badge">${naoLidas}</span>`:''}</span>
        <span class="chat-time">${hora}</span>
      </div>
      <div class="chat-preview">${ultima?.texto||''}</div>
    </div>`;
  }).join('');
}

function abrirChat(numero, nome) {
  chatAtual = numero;
  document.getElementById('chat-nome').textContent = nome;
  document.getElementById('chat-num').textContent = numero;
  // Marca como lidas
  if (conversas[numero]) {
    conversas[numero].msgs?.forEach(m => m.lida = true);
    fetch('/api/mensagens/lidas', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({numero})});
  }
  renderChat();
  document.getElementById('msg-lista-view').style.display='none';
  document.getElementById('msg-chat-view').style.display='block';
  // Navega para a página de mensagens
  showPage('mensagens', document.getElementById('nav-mensagens'));
  atualizarBadgeMsg();
}

function voltarLista() {
  chatAtual = null;
  document.getElementById('msg-lista-view').style.display='block';
  document.getElementById('msg-chat-view').style.display='none';
  carregarMensagens();
}

function renderChat() {
  const el = document.getElementById('chat-msgs');
  const conv = conversas[chatAtual];
  if (!conv || !conv.msgs?.length) { el.innerHTML='<div class="empty-state">Nenhuma mensagem ainda.</div>'; return; }
  el.innerHTML = conv.msgs.map(m => {
    const hora = new Date(m.ts).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
    return `<div class="msg-bubble ${m.dir==='recv'?'received':'sent'}">
      ${m.texto}
      <div class="msg-time">${hora}</div>
    </div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

async function enviarResposta() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg || !chatAtual) return;
  input.value = '';
  try {
    const r = await fetch('/api/whatsapp', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({telefone: chatAtual, mensagem: msg, salvar: true})
    });
    const d = await r.json();
    if (d.messages || d.ok) {
      if (!conversas[chatAtual]) conversas[chatAtual] = {numero: chatAtual, nome: chatAtual, msgs: []};
      conversas[chatAtual].msgs.push({dir:'sent', texto: msg, ts: Date.now(), lida: true});
      renderChat();
    } else {
      alert('Erro ao enviar: ' + (d.erro||JSON.stringify(d)));
    }
  } catch(e) { alert('Erro: ' + e); }
}

// Atualiza mensagens a cada 5 segundos
setInterval(async () => {
  if (document.getElementById('page-mensagens').classList.contains('active')) {
    await carregarMensagens();
    if (chatAtual) renderChat();
  } else {
    // Só atualiza badge
    try {
      const r = await fetch('/api/mensagens');
      conversas = await r.json();
      atualizarBadgeMsg();
    } catch(e) {}
  }
}, 5000);
// ─────────────────────────────────────────────────────────────────────────────

init();
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        parsed = urlparse(self.path)
        # Webhook verificação Meta
        if parsed.path == '/webhook':
            params = parse_qs(parsed.query)
            mode      = params.get('hub.mode',      [''])[0]
            token     = params.get('hub.verify_token', [''])[0]
            challenge = params.get('hub.challenge', [''])[0]
            if mode == 'subscribe' and token == WHATSAPP_VERIFY_TOKEN:
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(challenge.encode())
                print(f"✅ Webhook verificado!")
            else:
                self.send_response(403)
                self.end_headers()
            return
        # API mensagens
        if parsed.path == '/api/mensagens':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(mensagens_globais.get('conversas',{}), ensure_ascii=False).encode('utf-8'))
            return
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML.encode('utf-8'))
        elif self.path == '/api/clientes':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(dados_globais, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # Webhook recebe mensagens do Meta
        if self.path == '/webhook':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            try:
                for entry in body.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        for msg in value.get('messages', []):
                            remetente = msg.get('from', '')
                            texto = msg.get('text', {}).get('body', '')
                            if texto:
                                print(f"📩 Mensagem de {remetente}: {texto}")
                                conv = mensagens_globais['conversas']
                                if remetente not in conv:
                                    # Tenta encontrar nome do cliente
                                    nome = remetente
                                    for c in dados_globais.get('clientes', []):
                                        tel = ''.join(filter(str.isdigit, c.get('tel1','')))
                                        if not tel.startswith('55'): tel = '55' + tel
                                        if tel == remetente:
                                            nome = c.get('nome', remetente)
                                            break
                                    conv[remetente] = {'numero': remetente, 'nome': nome, 'msgs': []}
                                conv[remetente]['msgs'].append({
                                    'dir': 'recv',
                                    'texto': texto,
                                    'ts': int(time.time() * 1000),
                                    'lida': False
                                })
                                salvar_mensagens(mensagens_globais)
            except Exception as e:
                print(f"Erro webhook: {e}")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        # Enviar WhatsApp
        if self.path == '/api/whatsapp':
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            telefone = body.get('telefone', '')
            mensagem = body.get('mensagem', '')
            salvar = body.get('salvar', False)
            resultado = enviar_whatsapp(telefone, mensagem)
            # Salva mensagem enviada no histórico
            if salvar and (resultado.get('messages') or resultado.get('ok')):
                numero = ''.join(filter(str.isdigit, telefone))
                if not numero.startswith('55'): numero = '55' + numero
                conv = mensagens_globais['conversas']
                if numero not in conv:
                    conv[numero] = {'numero': numero, 'nome': numero, 'msgs': []}
                conv[numero]['msgs'].append({
                    'dir': 'sent', 'texto': mensagem,
                    'ts': int(time.time() * 1000), 'lida': True
                })
                salvar_mensagens(mensagens_globais)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resultado, ensure_ascii=False).encode('utf-8'))
            return

        # Marcar mensagens como lidas
        if self.path == '/api/mensagens/lidas':
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            numero = body.get('numero', '')
            if numero in mensagens_globais.get('conversas', {}):
                for m in mensagens_globais['conversas'][numero].get('msgs', []):
                    m['lida'] = True
                salvar_mensagens(mensagens_globais)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if self.path == '/api/salvar':
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            dados_globais['clientes'] = body['clientes']
            salvar_dados(dados_globais)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        elif self.path in ('/api/preview', '/api/preview_aba'):
            import io
            content_type = self.headers['Content-Type']
            boundary = content_type.split('boundary=')[-1].encode()
            length = int(self.headers['Content-Length'])
            body = self.rfile.read(length)
            
            # Parse multipart manualmente
            parts = body.split(b'--' + boundary)
            file_data = None
            aba = ''
            for part in parts:
                if b'filename=' in part:
                    idx = part.index(b'\r\n\r\n')
                    file_data = part[idx+4:].rstrip(b'\r\n--')
                elif b'name="aba"' in part:
                    idx = part.index(b'\r\n\r\n')
                    aba = part[idx+4:].rstrip(b'\r\n--').decode('utf-8')
            
            if self.path == '/api/preview_aba' and aba and file_data:
                import io as _io
                try:
                    xl = pd.ExcelFile(_io.BytesIO(file_data))
                    df = xl.parse(aba)
                    df = df.fillna('')
                    colunas = list(df.columns)
                    dados = df.to_dict(orient='records')
                    resp = json.dumps({'colunas': colunas, 'dados': dados}, ensure_ascii=False, default=str)
                except Exception as e:
                    resp = json.dumps({'erro': str(e)})
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(resp.encode('utf-8'))
                return
            
            import io
            try:
                file_bytes = io.BytesIO(file_data)
                # Detecta CSV
                if file_data[:2] in (b'\xff\xfe', b'\xfe\xff') or (b',' in file_data[:200] and b'<' not in file_data[:10]):
                    try:
                        df = pd.read_csv(io.BytesIO(file_data), encoding='utf-8', on_bad_lines='skip')
                        df = df.fillna('')
                        colunas = list(df.columns)
                        dados = df.to_dict(orient='records')
                        resp = json.dumps({'colunas': colunas, 'dados': dados, 'abas': [], 'aba_atual': ''}, ensure_ascii=False, default=str)
                    except:
                        df = pd.read_csv(io.BytesIO(file_data), encoding='latin-1', on_bad_lines='skip')
                        df = df.fillna('')
                        colunas = list(df.columns)
                        dados = df.to_dict(orient='records')
                        resp = json.dumps({'colunas': colunas, 'dados': dados, 'abas': [], 'aba_atual': ''}, ensure_ascii=False, default=str)
                else:
                    # Excel - retorna lista de abas para o usuario escolher
                    xl = pd.ExcelFile(io.BytesIO(file_data))
                    abas = xl.sheet_names
                    # Carrega a primeira aba por padrao
                    aba_atual = abas[0]
                    df = xl.parse(aba_atual)
                    df = df.fillna('')
                    colunas = list(df.columns)
                    dados = df.to_dict(orient='records')
                    resp = json.dumps({'colunas': colunas, 'dados': dados, 'abas': abas, 'aba_atual': aba_atual}, ensure_ascii=False, default=str)
            except Exception as e:
                resp = json.dumps({'erro': str(e)})
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(resp.encode('utf-8'))

def abrir_browser():
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{PORT}')

if __name__ == '__main__':
    print("=" * 50)
    print("  CRM - Gestão de Clientes")
    print("=" * 50)
    print(f"\n✅ Servidor rodando na porta {PORT}")
    is_local = not os.environ.get('RAILWAY_ENVIRONMENT')
    if is_local:
        print(f"   Acesse: http://localhost:{PORT}")
        threading.Thread(target=abrir_browser, daemon=True).start()
    print(f"\n⚠️  Não feche esta janela enquanto usar o CRM!")
    print(f"   Para fechar, pressione Ctrl+C\n")
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 CRM encerrado.")
