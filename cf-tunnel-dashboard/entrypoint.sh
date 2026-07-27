#!/bin/sh

AUTH_ENABLED=${DASHBOARD_AUTH_ENABLED:-true}
USERNAME=${BASIC_AUTH_USERNAME:-}
PASSWORD=${BASIC_AUTH_PASSWORD:-}

case "$AUTH_ENABLED" in
  true)
    if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
      echo "BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD must be set when DASHBOARD_AUTH_ENABLED=true" >&2
      exit 1
    fi
    printf '%s\n' "$PASSWORD" | htpasswd -i -B -c /etc/nginx/.htpasswd "$USERNAME"
    cat > /etc/nginx/conf.d/dashboard-auth.conf <<'EOF'
auth_basic "Cloudflare Tunnel Sync Dashboard";
auth_basic_user_file /etc/nginx/.htpasswd;
EOF
    ;;
  false)
    echo 'auth_basic off;' > /etc/nginx/conf.d/dashboard-auth.conf
    ;;
  *)
    echo "DASHBOARD_AUTH_ENABLED must be true or false" >&2
    exit 1
    ;;
esac

# Execute Nginx
exec nginx -g "daemon off;"
