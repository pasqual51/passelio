#!/bin/sh
# Run manually from the Unraid terminal when ready. Never starts application services.
set -eu
if [ "$(id -u)" != 0 ]; then echo "Run from the Unraid root terminal." >&2; exit 1; fi
PASSELIO_APPDATA=${PASSELIO_APPDATA:-/mnt/cache/appdata/passelio}
IMAGE=ghcr.io/pasqual51/passelio@sha256:a20c6244196a4332774c6fca6b886bb565ffd9be496fcab34c58f53600598526
pool=${PASSELIO_APPDATA#/mnt/}
pool=${pool%%/*}
case "$pool" in ''|user|user0|*[!A-Za-z0-9_-]*) echo 'Choose a direct local Unraid pool path, not /mnt/user.' >&2; exit 1;; esac
if [ "$PASSELIO_APPDATA" != "/mnt/$pool/appdata/passelio" ] || [ ! -d "/mnt/$pool/appdata" ]; then
  echo 'Expected /mnt/<existing-local-pool>/appdata/passelio. Create/pin your appdata share first.' >&2
  exit 1
fi
if [ -e "$PASSELIO_APPDATA" ] || [ -L "$PASSELIO_APPDATA" ]; then
  echo 'Target already exists. Nothing changed; do not overwrite an existing installation.' >&2
  exit 1
fi
docker pull "$IMAGE"
umask 077
mkdir -- "$PASSELIO_APPDATA"
for name in data backups secrets; do
  mkdir -- "$PASSELIO_APPDATA/$name"
  chown 10001:10001 "$PASSELIO_APPDATA/$name"
  chmod 700 "$PASSELIO_APPDATA/$name"
done
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --user 10001:10001 -v "$PASSELIO_APPDATA/secrets:/setup" --entrypoint python "$IMAGE" -c '
import os,secrets
fd=os.open("/setup/admin_password.txt",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
with os.fdopen(fd,"w") as output:output.write(secrets.token_urlsafe(32)+"\n")
print("Initial administrator secret created; application services have not been started.")
'
printf 'Data prepared at %s\nSecret: %s/secrets/admin_password.txt\n' "$PASSELIO_APPDATA" "$PASSELIO_APPDATA"
