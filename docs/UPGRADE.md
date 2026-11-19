# Upgrade and rollback

1. Read release notes and verify the intended image tag and digest. Alpha schema upgrades are not guaranteed backward compatible.
2. Stop web and worker together. Make a verified full backup and keep a separate encrypted copy of the original data volume and your deployment configuration/secrets.
3. Keep the old image digest. Build the new revision, or pull its versioned GHCR image if your account has package access. Never use an unversioned `latest` tag for an alpha deployment.
4. Recreate web and worker from the same image, retaining the data and backup volumes. Initial database migrations run at startup. Do not run different application versions concurrently during migration.
5. Check `/api/health`, login, admin settings, upload/download checksums, SMTP and configured storage. Inspect worker delivery/cleanup status. Leave optional registration/providers disabled until intentionally configured.
6. On failure stop both services. Restore the pre-upgrade backup into a **new** data directory using `backup.py restore`, validate it, and use the previous image and original secret/config mounts. Do not run an old binary against a migrated database or overwrite the only surviving data volume.

Full backup restore normalizes remote objects to local files. Verify available disk space first. Provider credentials are deliberately not restored; reconnect external identities using the same client/tenant and a fresh secret. Remote storage needs explicit configuration again.

## Mise à jour

Arrêtez ensemble le serveur web et le worker, sauvegardez et vérifiez l’ensemble des données et conservez l’ancienne image. Utilisez la même version pour les deux services. Après migration, testez connexion, dépôt/téléchargement, SMTP et stockage. Pour revenir en arrière, restaurez la sauvegarde dans un nouveau dossier avec l’ancienne image ; ne réutilisez pas une base migrée avec un ancien programme.
