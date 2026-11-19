# Accounts and identity providers

Public registration is disabled by default. In **Administration → System settings → Authentication**, enable SMTP first, then choose whether to allow registration and optionally restrict email domains. An email link lets its owner choose a password; an attacker cannot preassign a working password to another person's email address. Links expire and are single-use.

In **My profile**, email changes require the current password and, when enabled, a TOTP/recovery code. The old email remains valid until the new address is confirmed. Confirmation closes existing sessions and alerts the old address.

Google and Microsoft are opt-in OIDC providers configured in the same administration section. Register a confidential web application with the provider. Copy the exact displayed HTTPS callback URL, enter its client ID and secret, and for Microsoft enter the tenant UUID (single tenant). Secrets are stored in private files and never returned by the API. Blank secret fields preserve the saved secret. Create credentials in your own provider tenant; no credentials are bundled with Passelio.

Existing users must first sign in with their local account, then explicitly **Link** the provider under My profile. Identical email addresses do not automatically associate accounts. Subsequent provider sign-in still requires local MFA when enabled. Local passwords remain usable. Disabling a provider leaves password login available. A linked provider's client/tenant cannot be silently replaced.

Full restore disables providers and removes their secrets from the restored database. Re-enter the same client ID/tenant and a current secret before enabling them again. Existing identity mappings are retained. Provider flow/session challenges are never restored.

Individual quotas are under **Administration → Users → Individual quota**. Enter a whole number of GB or leave empty to inherit the global limit. Quotas reserve space transactionally, including unfinished uploads and upload requests; they do not allocate or resize a physical disk.

## Français

L’inscription publique et les fournisseurs externes sont désactivés par défaut. Leurs paramètres sont dans **Administration → Paramètres du système → Authentification**. SMTP est requis pour l’inscription et les changements d’adresse. Le propriétaire de l’adresse choisit son mot de passe depuis un lien à usage unique. L’ancienne adresse reste utilisée tant que la nouvelle n’est pas confirmée.

Créez une application web chez Google ou Microsoft, recopiez l’URL de retour affichée et renseignez l’identifiant et le secret client. Microsoft nécessite un identifiant de tenant UUID. Chaque utilisateur associe ensuite explicitement son compte depuis **Mon profil**. La double authentification locale reste exigée. Après restauration, renseignez à nouveau le secret du fournisseur avant de le réactiver.

Les quotas individuels se règlent dans **Utilisateurs → Quota individuel**, en Go entiers. Une valeur vide hérite du quota global. Ces limites ne redimensionnent pas le disque.
