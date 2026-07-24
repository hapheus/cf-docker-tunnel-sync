import os
import re
import json
import time
import asyncio
import logging
import urllib.request
import urllib.error
import socket
import http.client
import secrets
from typing import List, Dict

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cf-tunnel-sync")

app = FastAPI(title="Cloudflare Tunnel & DNS Sync")

security = HTTPBasic()

sync_state = {
    "last_sync": None,
    "status": "Initializing",
    "tunnel_id": None,
    "tunnel_name": os.getenv("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync"),
    "domain_name": os.getenv("DOMAIN_NAME", "fraha.dev"),
    "discovered_services": [],
    "all_containers": [],
    "dns_records": [],
    "logs": []
}

def add_log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    logger.info(msg)
    sync_state["logs"].insert(0, entry)
    if len(sync_state["logs"]) > 100:
        sync_state["logs"].pop()

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("BASIC_AUTH_USERNAME", "admin")
    correct_password = os.getenv("BASIC_AUTH_PASSWORD", "admin")
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__('localhost')
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)

def docker_api(path: str, method: str = 'GET', data: dict = None) -> dict:
    conn = UnixHTTPConnection('/var/run/docker.sock')
    headers = {}
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(data).encode('utf-8')
    
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read().decode('utf-8')
    conn.close()
    if resp_data:
        try:
            return json.loads(resp_data)
        except Exception:
            return {"raw": resp_data}
    return {}

def cf_api(endpoint: str, token: str, method: str = 'GET', data: dict = None) -> dict:
    url = f"https://api.cloudflare.com/client/v4{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def get_docker_containers() -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    services = []
    all_containers = []
    try:
        containers = docker_api('/containers/json?all=true')
        if isinstance(containers, list):
            for c in containers:
                labels = c.get('Labels', {})
                c_names = c.get('Names', ['/unknown'])
                c_name = c_names[0].lstrip('/') if c_names else 'unknown'
                state = c.get('State', 'unknown')
                status_text = c.get('Status', '')
                image = c.get('Image', '')

                hostname = labels.get('cf.tunnel.hostname') or labels.get('cf.tunnel.domain') or labels.get('cloudflared.hostname')

                is_tunneled = False
                service_url = ""

                if hostname and state == "running":
                    is_tunneled = True
                    service_url = labels.get('cf.tunnel.service')
                    port = labels.get('cf.tunnel.port')
                    if not service_url:
                        if port:
                            service_url = f"http://{c_name}:{port}"
                        else:
                            ports = c.get('Ports', [])
                            if ports:
                                p = ports[0].get('PrivatePort', 80)
                                service_url = f"http://{c_name}:{p}"
                            else:
                                service_url = f"http://{c_name}:80"

                    services.append({
                        "container": c_name,
                        "hostname": hostname,
                        "service": service_url
                    })

                all_containers.append({
                    "name": c_name,
                    "image": image,
                    "state": state,
                    "status": status_text,
                    "hostname": hostname if hostname else "-",
                    "is_tunneled": is_tunneled
                })
    except Exception as e:
        add_log(f"Docker API Error: {e}")
    return services, all_containers

def run_sync_logic():
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    domain = os.getenv("DOMAIN_NAME", "fraha.dev")
    tunnel_name = os.getenv("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")

    sync_state["status"] = "Syncing..."
    sync_state["domain_name"] = domain
    sync_state["tunnel_name"] = tunnel_name

    if not token or token == "your_cloudflare_api_token_here":
        sync_state["status"] = "Waiting for CLOUDFLARE_API_TOKEN in .env"
        add_log("⚠️ CLOUDFLARE_API_TOKEN missing or default placeholder in .env!")
        return

    try:
        # 1. Account ID
        if not account_id:
            acc_resp = cf_api("/accounts", token)
            accounts = acc_resp.get("result", [])
            if not accounts:
                add_log("❌ No Cloudflare accounts found for this token!")
                sync_state["status"] = "Error: No Account"
                return
            account_id = accounts[0]["id"]

        # 2. Zone ID
        zones_resp = cf_api(f"/zones?name={domain}", token)
        zones = zones_resp.get("result", [])
        if not zones:
            add_log(f"❌ Zone for domain '{domain}' not found in Cloudflare!")
            sync_state["status"] = f"Error: Zone {domain} missing"
            return
        zone_id = zones[0]["id"]

        # 3. Tunnel
        tunnels_resp = cf_api(f"/accounts/{account_id}/cfd_tunnel?name={tunnel_name}&is_deleted=false", token)
        tunnels = tunnels_resp.get("result", [])
        if tunnels:
            tunnel_id = tunnels[0]["id"]
        else:
            add_log(f"🔨 Creating Cloudflare Tunnel '{tunnel_name}'...")
            cr_resp = cf_api(f"/accounts/{account_id}/cfd_tunnel", token, method="POST", data={
                "name": tunnel_name,
                "config_src": "cloudflare"
            })
            tunnel_id = cr_resp["result"]["id"]
            add_log(f"✅ Created Tunnel: {tunnel_id}")

        sync_state["tunnel_id"] = tunnel_id

        # 4. Retrieve Tunnel Token & write to shared volume for cloudflared
        token_resp = cf_api(f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token", token)
        tunnel_token = token_resp["result"]

        token_path = "/etc/cloudflared/token"
        old_token = ""
        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    old_token = f.read().strip()
            except Exception:
                pass

        if old_token != tunnel_token:
            os.makedirs("/etc/cloudflared", exist_ok=True)
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(tunnel_token)
            add_log("🔑 Updated Cloudflare Tunnel Token in shared volume")
            
            try:
                docker_api('/containers/cloudflared/restart', method='POST')
                add_log("🔄 Triggered restart for cloudflared container")
            except Exception as re:
                add_log(f"Notice restarting cloudflared: {re}")

        # 5. Discover Docker services
        services, all_containers = get_docker_containers()
        sync_state["discovered_services"] = services
        sync_state["all_containers"] = all_containers
        
        discovered_names = [f"{s['hostname']} ({s['service']})" for s in services]
        add_log(f"🔍 Discovered Cloudflare-labeled services: {', '.join(discovered_names) if services else 'None'}")

        # 6. Build Cloudflare Tunnel Ingress Rules
        ingress_rules = []
        for s in services:
            ingress_rules.append({
                "hostname": s["hostname"],
                "service": s["service"]
            })
        ingress_rules.append({"service": "http_status:404"})

        cf_api(f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", token, method="PUT", data={
            "config": {"ingress": ingress_rules}
        })
        add_log("✅ Updated Cloudflare Tunnel Ingress rules")

        # 7. DNS Records Sync (CNAME per subdomain)
        target_cname = f"{tunnel_id}.cfargotunnel.com"
        synced_dns = []
        for s in services:
            host = s["hostname"]
            dns_resp = cf_api(f"/zones/{zone_id}/dns_records?type=CNAME&name={host}", token)
            records = dns_resp.get("result", [])
            dns_payload = {
                "type": "CNAME",
                "name": host,
                "content": target_cname,
                "proxied": True,
                "ttl": 1
            }
            if records:
                rec_id = records[0]["id"]
                cf_api(f"/zones/{zone_id}/dns_records/{rec_id}", token, method="PUT", data=dns_payload)
            else:
                cf_api(f"/zones/{zone_id}/dns_records", token, method="POST", data=dns_payload)
            synced_dns.append({"hostname": host, "target": target_cname, "service": s["service"], "proxied": True})

        # 8. Clean up obsolete CNAME records pointing to this tunnel
        active_hostnames = {s["hostname"] for s in services}
        try:
            all_dns_resp = cf_api(f"/zones/{zone_id}/dns_records?type=CNAME&content={target_cname}", token)
            all_records = all_dns_resp.get("result", [])
            for record in all_records:
                rec_name = record["name"]
                if rec_name not in active_hostnames:
                    add_log(f"🧹 Deleting obsolete Cloudflare DNS record: {rec_name}")
                    cf_api(f"/zones/{zone_id}/dns_records/{record['id']}", token, method="DELETE")
        except Exception as de:
            add_log(f"⚠️ Error cleaning up obsolete DNS records: {de}")

        sync_state["dns_records"] = synced_dns
        sync_state["status"] = "Active / Synced"
        sync_state["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
        add_log("🎉 Sync completed successfully!")

    except Exception as e:
        sync_state["status"] = f"Error: {str(e)}"
        add_log(f"❌ Sync Error: {e}")

async def sync_loop():
    while True:
        try:
            run_sync_logic()
        except Exception as e:
            add_log(f"Loop Exception: {e}")
        poll_interval = int(os.getenv("POLL_INTERVAL", "30"))
        await asyncio.sleep(poll_interval)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(sync_loop())

@app.get("/api/status")
def api_status(username: str = Depends(authenticate)):
    return JSONResponse(sync_state)

@app.post("/api/sync")
def api_sync(username: str = Depends(authenticate)):
    run_sync_logic()
    return JSONResponse({"message": "Sync triggered", "state": sync_state})

HTML_PAGE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cloudflare Tunnel & Docker Sync</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Outfit', 'sans-serif'],
                        mono: ['Fira Code', 'monospace'],
                    },
                    colors: {
                        brand: {
                            500: '#f97316',
                            600: '#ea580c',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body {
            font-family: 'Outfit', sans-serif;
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
    <div class="max-w-7xl mx-auto px-4 py-8">
        <!-- Header -->
        <header class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
            <div>
                <h1 class="text-3xl font-extrabold flex items-center gap-3">
                    <span class="text-orange-500">☁️ Cloudflare Tunnel Sync</span>
                </h1>
                <p class="text-slate-400 text-sm mt-1">Automatic Docker service discovery & DNS synchronization via Cloudflare Zero Trust</p>
            </div>
            <div class="flex items-center gap-3">
                <span id="status-badge" class="px-3 py-1 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                    Initializing...
                </span>
                <button onclick="triggerSync()" id="sync-btn" class="bg-orange-600 hover:bg-orange-500 text-white text-sm font-medium px-4 py-2.5 rounded-lg transition-all shadow-lg shadow-orange-950/20 flex items-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                    Sync Now
                </button>
            </div>
        </header>

        <!-- Main Stats Grid -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 my-8">
            <div class="bg-slate-900/60 backdrop-blur border border-slate-800 rounded-xl p-5 shadow-sm">
                <div class="text-xs uppercase tracking-wider text-slate-500 font-bold">Tunnel Name</div>
                <div class="text-xl font-bold text-slate-100 mt-2" id="tunnel-name">-</div>
                <div class="text-xs text-slate-400 mt-1 font-mono" id="tunnel-id">ID: -</div>
            </div>

            <div class="bg-slate-900/60 backdrop-blur border border-slate-800 rounded-xl p-5 shadow-sm">
                <div class="text-xs uppercase tracking-wider text-slate-500 font-bold">Domain Name</div>
                <div class="text-xl font-bold text-slate-100 mt-2" id="domain-name">-</div>
                <div class="text-xs text-orange-400 mt-1">Cloudflare Managed</div>
            </div>

            <div class="bg-slate-900/60 backdrop-blur border border-slate-800 rounded-xl p-5 shadow-sm">
                <div class="text-xs uppercase tracking-wider text-slate-500 font-bold">Last Synchronization</div>
                <div class="text-xl font-bold text-slate-100 mt-2" id="last-sync">-</div>
                <div class="text-xs text-slate-400 mt-1">Interval: every 30s</div>
            </div>
        </div>

        <!-- Layout -->
        <div class="space-y-8">
            <!-- Discovered Hostnames Section -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <h2 class="text-lg font-bold mb-4 flex items-center gap-2">
                    <span>🐳 Docker Container Status & Cloudflare Routing</span>
                </h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm">
                        <thead class="text-xs text-slate-400 uppercase bg-slate-950/50 border-b border-slate-800">
                            <tr>
                                <th class="px-4 py-3">Container</th>
                                <th class="px-4 py-3">Image</th>
                                <th class="px-4 py-3">Status</th>
                                <th class="px-4 py-3">Subdomain / Public Hostname</th>
                                <th class="px-4 py-3">Cloudflare DNS</th>
                            </tr>
                        </thead>
                        <tbody id="hosts-tbody" class="divide-y divide-slate-800 text-slate-300 font-mono text-xs">
                            <tr>
                                <td colspan="5" class="px-4 py-6 text-center text-slate-500 font-sans">Searching for containers...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Live Log Panel -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <h2 class="text-lg font-bold mb-4 flex items-center justify-between">
                    <span>📜 Live Event Log</span>
                    <span class="text-xs font-mono text-slate-500">Auto-refresh</span>
                </h2>
                <div id="logs-container" class="bg-slate-950 font-mono text-xs p-4 rounded-lg h-60 overflow-y-auto space-y-1 text-slate-300 border border-slate-800/80">
                    <div class="text-slate-500">Waiting for events...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (res.status === 401) {
                    window.location.reload();
                    return;
                }
                const data = await res.json();
                
                document.getElementById('status-badge').innerText = data.status;
                if (data.status.includes('Active') || data.status.includes('Synced')) {
                    document.getElementById('status-badge').className = 'px-3 py-1 text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
                } else if (data.status.includes('Error')) {
                    document.getElementById('status-badge').className = 'px-3 py-1 text-xs font-semibold rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30';
                } else {
                    document.getElementById('status-badge').className = 'px-3 py-1 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30';
                }

                document.getElementById('tunnel-name').innerText = data.tunnel_name || '-';
                document.getElementById('tunnel-id').innerText = data.tunnel_id ? `ID: ${data.tunnel_id.substring(0, 18)}...` : 'ID: -';
                document.getElementById('domain-name').innerText = data.domain_name || '-';
                document.getElementById('last-sync').innerText = data.last_sync || 'Never';

                const tbody = document.getElementById('hosts-tbody');
                if (data.all_containers && data.all_containers.length > 0) {
                    tbody.innerHTML = data.all_containers.map(c => {
                        let statusBadge = '';
                        if (c.state === 'running') {
                            statusBadge = `<span class="px-2 py-0.5 text-xs rounded bg-emerald-950 text-emerald-400 border border-emerald-800">Running</span>`;
                        } else {
                            statusBadge = `<span class="px-2 py-0.5 text-xs rounded bg-rose-950 text-rose-400 border border-rose-800">${c.state}</span>`;
                        }

                        let tunnelInfo = '<span class="text-slate-600 font-sans text-xs italic">-</span>';
                        let dnsInfo = '<span class="text-slate-600 font-sans text-xs italic">-</span>';
                        
                        if (c.is_tunneled) {
                            tunnelInfo = `<a href="https://${c.hostname}" target="_blank" class="text-orange-400 hover:underline flex items-center gap-1.5 font-semibold">
                                ${c.hostname}
                                <svg class="w-3.5 h-3.5 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                            </a>`;
                            dnsInfo = `<span class="text-emerald-400 font-semibold">Active & Synced</span>`;
                        } else if (c.hostname !== '-') {
                            tunnelInfo = `<span class="text-slate-500 line-through">${c.hostname}</span>`;
                            dnsInfo = `<span class="text-slate-500 font-sans italic text-xs">Stopped (Inactive)</span>`;
                        }

                        return `
                            <tr class="hover:bg-slate-800/50">
                                <td class="px-4 py-3 font-sans font-medium text-slate-200">${c.name}</td>
                                <td class="px-4 py-3 text-slate-400 text-xs">${c.image}</td>
                                <td class="px-4 py-3">${statusBadge}</td>
                                <td class="px-4 py-3">${tunnelInfo}</td>
                                <td class="px-4 py-3">${dnsInfo}</td>
                            </tr>
                        `;
                    }).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="5" class="px-4 py-6 text-center text-slate-500 font-sans">No containers found.</td></tr>';
                }

                const logContainer = document.getElementById('logs-container');
                if (data.logs && data.logs.length > 0) {
                    logContainer.innerHTML = data.logs.map(log => `<div>${log}</div>`).join('');
                }
            } catch (err) {
                console.error("Fetch status error:", err);
            }
        }

        async function triggerSync() {
            const btn = document.getElementById('sync-btn');
            btn.disabled = true;
            btn.classList.add('opacity-50');
            try {
                await fetch('/api/sync', { method: 'POST' });
                await fetchStatus();
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50');
            }
        }

        setInterval(fetchStatus, 3000);
        fetchStatus();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index(username: str = Depends(authenticate)):
    return HTML_PAGE

if __name__ == '__main__':
    uvicorn.run("app:app", host="0.0.0.0", port=8090)
