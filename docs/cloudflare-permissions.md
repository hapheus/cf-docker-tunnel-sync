# Cloudflare Scoped API Token Guide (Least Privilege)

This guide walks you through creating a **least-privilege, scoped API token** in Cloudflare.

> [!CAUTION]
> **Never use your Global API Key!**  
> Global API Keys grant unrestricted administrative access to your entire Cloudflare account, billing details, and all zones. `cf-docker-tunnel-sync` only requires scoped permissions for Tunnels and DNS.

---

## 📋 Required Permissions Matrix

| Scope | Resource | Permission | Why Is It Needed? |
| :--- | :--- | :--- | :--- |
| **Account** | `Cloudflare Tunnel` | **Edit** | Creates and manages named tunnels, retrieves the tunnel token, and configures ingress rules. |
| **Zone** | `DNS` | **Edit** | Creates, updates, and safely cleans up CNAME records for your exposed container hostnames. |
| **Zone** | `Zone` | **Read** | Resolves domain names (e.g. `example.com`) to their corresponding `Zone ID`. |

---

## 🛠️ Step-by-Step Walkthrough

### Step 1: Navigate to API Tokens
1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. In the top-right profile dropdown, click **My Profile**.
3. Select **API Tokens** from the left navigation.
4. Click **Create Token**.

### Step 2: Create a Custom Token
1. Scroll to the bottom and click **Create Custom Token** (do not use predefined templates).
2. Set a descriptive Token Name, e.g. `cf-docker-tunnel-sync-gateway`.

### Step 3: Configure Token Permissions
Under **Permissions**, add the following three entries:
* `Account` | `Cloudflare Tunnel` | `Edit`
* `Zone` | `DNS` | `Edit`
* `Zone` | `Zone` | `Read`

### Step 4: Configure Resource Scoping
* **Account Resources:** Select `Include` → `All accounts` (or your specific account).
* **Zone Resources:** Select `Include` → `Specific zone` → select your target domain (or `All zones`).

![Cloudflare Token Setup](screenshots/cloudflare-token-setup.png)

### Step 5: Generate & Verify Token
Click **Continue to summary** → **Create Token**. Copy the displayed token.

Verify the token validity and permissions from your server terminal:

```bash
curl -s -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
     -H "Authorization: Bearer YOUR_GENERATED_API_TOKEN" \
     -H "Content-Type: application/json" | jq .
```

Expected output:
```json
{
  "result": {
    "id": "...",
    "status": "active"
  },
  "success": true,
  "errors": [],
  "messages": [
    {
      "code": 10000,
      "message": "This API Token is valid and active"
    }
  ]
}
```
