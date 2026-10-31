#!/bin/sh

AUTH_ENABLED=${DASHBOARD_AUTH_ENABLED:-true}
USERNAME=${DASHBOARD_USERNAME:-${BASIC_AUTH_USERNAME:-}}
PASSWORD=${DASHBOARD_PASSWORD:-${BASIC_AUTH_PASSWORD:-}}

if [ -n "$BASIC_AUTH_USERNAME" ] && [ -z "$DASHBOARD_USERNAME" ]; then
  echo "Configuration note: 'BASIC_AUTH_USERNAME' is deprecated and will be removed in a future release. Please use 'DASHBOARD_USERNAME' instead." >&2
fi
if [ -n "$BASIC_AUTH_PASSWORD" ] && [ -z "$DASHBOARD_PASSWORD" ]; then
  echo "Configuration note: 'BASIC_AUTH_PASSWORD' is deprecated and will be removed in a future release. Please use 'DASHBOARD_PASSWORD' instead." >&2
fi

mkdir -p /etc/nginx/snippets

case "$AUTH_ENABLED" in
  true)
    if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
      echo "BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD must be set when DASHBOARD_AUTH_ENABLED=true (or use DASHBOARD_USERNAME and DASHBOARD_PASSWORD)" >&2
      exit 1
    fi
    printf '%s\n' "$PASSWORD" | htpasswd -i -B -c /etc/nginx/.htpasswd "$USERNAME"
    cat > /etc/nginx/snippets/dashboard-auth.conf <<'EOF'
auth_basic "Cloudflare Tunnel Sync Dashboard";
auth_basic_user_file /etc/nginx/.htpasswd;
EOF
    ;;
  false)
    echo 'auth_basic off;' > /etc/nginx/snippets/dashboard-auth.conf
    ;;
  *)
    echo "DASHBOARD_AUTH_ENABLED must be true or false" >&2
    exit 1
    ;;
esac

BACKEND_HOST=${SYNC_BACKEND_HOST:-cf-tunnel-sync}
BACKEND_PORT=${SYNC_BACKEND_PORT:-8090}

cat > /etc/nginx/snippets/sync-backend.conf <<EOF
location /api/ {
    proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT}/api/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
EOF

# Execute Nginx
exec nginx -g "daemon off;"


