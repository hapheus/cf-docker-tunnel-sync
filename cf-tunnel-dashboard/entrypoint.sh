#!/bin/sh

# Set defaults if not provided
USERNAME=${BASIC_AUTH_USERNAME:-admin}
PASSWORD=${BASIC_AUTH_PASSWORD:-admin}

# Generate htpasswd file
htpasswd -b -c /etc/nginx/.htpasswd "$USERNAME" "$PASSWORD"

# Execute Nginx
exec nginx -g "daemon off;"
