FROM nginx:alpine@sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11

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
