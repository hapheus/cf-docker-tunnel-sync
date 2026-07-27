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
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cf-tunnel-sync")

app = FastAPI(title="Cloudflare Tunnel & DNS Sync")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

@app.get("/health")
def health():
    return {"status": "healthy", "sync_status": sync_state["status"]}

@app.get("/api/status")
def api_status():
    return JSONResponse(sync_state)

@app.post("/api/sync")
def api_sync():
    run_sync_logic()
    return JSONResponse({"message": "Sync triggered", "state": sync_state})

if __name__ == '__main__':
    uvicorn.run("app:app", host="0.0.0.0", port=8090)
