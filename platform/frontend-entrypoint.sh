#!/bin/sh
# DKMV Platform — production frontend (nginx) entrypoint (G14).
#
# Renders `nginx.conf.template` → the live nginx config at container start,
# substituting ONLY the DKMV vars (the backend upstream + the control-plane
# token). nginx's own runtime variables ($http_host, $uri, $dkmv_auth, …) MUST
# survive untouched, so we do an EXPLICIT, whitelisted substitution with
# `envsubst '<list>'` (which replaces only the named vars and leaves every other
# `$name` verbatim) — never a bare `envsubst` (that would clobber nginx vars).
set -eu

# Backend origin the dev proxy uses (vite.config.ts DKMV_BACKEND_ORIGIN). In
# compose this is http://backend:8787. nginx `upstream` wants a bare host:port,
# so strip the scheme to derive DKMV_BACKEND_UPSTREAM.
: "${DKMV_BACKEND_ORIGIN:=http://backend:8787}"
: "${DKMV_PLATFORM_TOKEN:=}"

# Strip http:// or https:// → host:port for the `upstream server` directive.
DKMV_BACKEND_UPSTREAM=$(printf '%s' "$DKMV_BACKEND_ORIGIN" | sed -E 's#^https?://##')
export DKMV_BACKEND_UPSTREAM DKMV_PLATFORM_TOKEN

if [ -z "$DKMV_PLATFORM_TOKEN" ]; then
  # Mirror the dev proxy: with no token, the proxy injects nothing and the user
  # is expected to rely on the cookie / pass their own Authorization. Warn loudly
  # so a misconfigured deploy is obvious (the API will 401 most calls).
  echo "WARN [dkmv-frontend] DKMV_PLATFORM_TOKEN is empty — proxied /api requests" \
       "will carry no injected Bearer token and the backend will reject them (INV-1)." >&2
fi

# Render ONLY our two vars; nginx '$'-vars are preserved because they are not in
# the substitution list.
envsubst '${DKMV_BACKEND_UPSTREAM} ${DKMV_PLATFORM_TOKEN}' \
  < /etc/nginx/templates/nginx.conf.template \
  > /etc/nginx/conf.d/default.conf

# Validate the rendered config before handing off to nginx (fail-fast on a bad
# template render rather than a half-started server).
nginx -t

exec "$@"
