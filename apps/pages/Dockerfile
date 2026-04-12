FROM nginx:alpine

# Install python3 for gen-index.sh metadata parsing
RUN apk add --no-cache python3

# Copy gen-index script to /usr/local/bin (outside the NFS-mounted HTML dir)
COPY scripts/gen-index.sh /usr/local/bin/gen-index.sh
RUN chmod +x /usr/local/bin/gen-index.sh

# Custom nginx config
RUN echo 'server { \
    listen 80; \
    server_name _; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
    add_header X-Content-Type-Options "nosniff" always; \
    add_header X-Frame-Options "SAMEORIGIN" always; \
    add_header Referrer-Policy "strict-origin-when-cross-origin" always; \
}' > /etc/nginx/conf.d/default.conf

# Generate initial index on startup, then start nginx
CMD ["/bin/sh", "-c", "/usr/local/bin/gen-index.sh && nginx -g 'daemon off;'"]