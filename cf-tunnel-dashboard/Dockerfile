FROM nginx:alpine@sha256:fb4658584bd9a916ffb6f6e365f97c25cfdb2923801f551ea08356e695f14ff7

# Install apache2-utils for htpasswd tool
RUN apk add --no-cache apache2-utils

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html dashboard.js dashboard.css /usr/share/nginx/html/
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    mkdir -p /etc/nginx/snippets && \
    touch /etc/nginx/snippets/dashboard-auth.conf && \
    printf 'location /api/ {\n    proxy_pass http://cf-tunnel-sync:8090/api/;\n}\n' > /etc/nginx/snippets/sync-backend.conf



ENTRYPOINT ["/entrypoint.sh"]
