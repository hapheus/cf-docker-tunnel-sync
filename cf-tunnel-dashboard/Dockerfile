FROM nginx:alpine@sha256:fed7e14be83cbd2661a75cdc5b872d936cf155d46c327084d30b8df19ae88d72

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
