#!/bin/sh
set -e

# LinuxServer.io-style PUID/PGID handling
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "
───────────────────────────────────────
  Audiobook Organizer
───────────────────────────────────────
  User UID: ${PUID}
  User GID: ${PGID}
───────────────────────────────────────
"

# Remove existing abc user/group if they exist
if getent group abc > /dev/null 2>&1; then
    groupdel abc 2>/dev/null || true
fi
if id abc > /dev/null 2>&1; then
    userdel abc 2>/dev/null || true
fi

# Remove any user/group with conflicting IDs
existing_user=$(getent passwd "${PUID}" | cut -d: -f1 2>/dev/null || true)
if [ -n "$existing_user" ] && [ "$existing_user" != "abc" ]; then
    userdel "$existing_user" 2>/dev/null || true
fi
existing_group=$(getent group "${PGID}" | cut -d: -f1 2>/dev/null || true)
if [ -n "$existing_group" ] && [ "$existing_group" != "abc" ]; then
    groupdel "$existing_group" 2>/dev/null || true
fi

# Create abc group and user
addgroup -g "${PGID}" abc
adduser -u "${PUID}" -G abc -D -h /app abc

# Set ownership of writable directories
chown -R abc:abc /app/data
chown -R abc:abc /var/lib/nginx
chown -R abc:abc /var/log/nginx
chown -R abc:abc /run/nginx 2>/dev/null || mkdir -p /run/nginx && chown -R abc:abc /run/nginx

# Set ownership of audiobook directories if they exist
[ -d /downloads ] && chown abc:abc /downloads
[ -d /library ] && chown abc:abc /library

# Start uvicorn as abc user in background
echo "Starting backend server..."
su abc -s /bin/sh -c "cd /app && DATABASE_URL=${DATABASE_URL:-sqlite:////app/data/audiobook_organizer.db} uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1" &

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
        echo "Backend ready."
        break
    fi
    sleep 1
done

# Start nginx in foreground
echo "Starting nginx..."
exec nginx -g "daemon off;"
