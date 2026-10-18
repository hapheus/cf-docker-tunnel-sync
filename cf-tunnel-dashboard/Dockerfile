FROM nginx:alpine

# Install apache2-utils for htpasswd tool
RUN apk add --no-cache apache2-utils

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    mkdir -p /etc/nginx/snippets && \
    touch /etc/nginx/snippets/dashboard-auth.conf && \
    printf 'location /api/ {\n    proxy_pass http://cf-tunnel-sync:8090/api/;\n}\n' > /etc/nginx/snippets/sync-backend.conf



ENTRYPOINT ["/entrypoint.sh"]
