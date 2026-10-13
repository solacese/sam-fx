#!/usr/bin/env python3
"""Create the FX Keycloak realm and Kubernetes Secrets without printing credentials."""

from __future__ import annotations

import base64
import json
import secrets
import subprocess
from pathlib import Path

NAMESPACE = "sam-fx"
OUTPUT = Path(".credentials/keycloak-users.txt")


def password() -> str:
    return secrets.token_urlsafe(24)


def kubectl_apply(resource: dict[str, object]) -> None:
    subprocess.run(
        ["kubectl", "apply", "--server-side", "--field-manager=sam-fx-setup", "-f", "-"],
        input=json.dumps(resource),
        text=True,
        check=True,
    )


def existing_secret(name: str) -> dict[str, str]:
    result = subprocess.run(
        ["kubectl", "get", "secret", name, "-n", NAMESPACE, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return {}
    encoded = json.loads(result.stdout).get("data", {})
    return {key: base64.b64decode(value).decode() for key, value in encoded.items()}


def secret(name: str, data: dict[str, str]) -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": NAMESPACE},
        "type": "Opaque",
        "stringData": data,
    }


def main() -> None:
    prior_keycloak = existing_secret("keycloak-secrets")
    prior_database = existing_secret("keycloak-db")
    prior_oauth = existing_secret("fx-oauth")
    prior_users = (
        dict(line.split("=", 1) for line in OUTPUT.read_text().splitlines() if "=" in line)
        if OUTPUT.exists()
        else {}
    )
    admin_password = prior_keycloak.get("admin-password", password())
    database_password = prior_database.get("password", password())
    client_secret = prior_oauth.get("client-secret", password())
    cookie_secret = prior_oauth.get(
        "cookie-secret", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    )
    user_passwords = {
        email: prior_users.get(email, password())
        for email in ("raphael.caillon@solace.com", "jamil.ahmed@solace.com")
    }
    realm = {
        "realm": "fx",
        "enabled": True,
        "displayName": "FX Regime Agent",
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": True,
        "clients": [
            {
                "clientId": "fx-dashboard",
                "name": "FX Regime Dashboard",
                "enabled": True,
                "clientAuthenticatorType": "client-secret",
                "secret": client_secret,
                "redirectUris": ["https://fx.sol-se-emea.com/oauth2/callback"],
                "webOrigins": ["https://fx.sol-se-emea.com"],
                "publicClient": False,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "protocol": "openid-connect",
                "attributes": {"pkce.code.challenge.method": "S256"},
                "defaultClientScopes": ["profile", "email", "roles", "basic"],
            },
            {
                "clientId": "sam-webui",
                "name": "Solace Agent Mesh",
                "enabled": True,
                "clientAuthenticatorType": "client-secret",
                "secret": client_secret,
                "redirectUris": ["https://mesh.fx.sol-se-emea.com/api/v1/auth/callback"],
                "webOrigins": ["https://mesh.fx.sol-se-emea.com"],
                "publicClient": False,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": True,
                "protocol": "openid-connect",
                "defaultClientScopes": ["profile", "email", "roles", "basic"],
            },
        ],
        "users": [
            {
                "username": email,
                "email": email,
                "firstName": email.split(".", 1)[0].title(),
                "lastName": email.split(".", 1)[1].split("@", 1)[0].title(),
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
                "credentials": [{"type": "password", "value": value, "temporary": False}],
            }
            for email, value in user_passwords.items()
        ],
    }
    kubectl_apply(
        secret(
            "keycloak-secrets",
            {
                "admin-username": "admin",
                "admin-password": admin_password,
                "client-secret": client_secret,
            },
        )
    )
    kubectl_apply(secret("keycloak-db", {"username": "keycloak", "password": database_password}))
    kubectl_apply(
        secret("fx-oauth", {"client-secret": client_secret, "cookie-secret": cookie_secret})
    )
    kubectl_apply(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "keycloak-realm", "namespace": NAMESPACE},
            "type": "Opaque",
            "stringData": {"fx-realm.json": json.dumps(realm)},
        }
    )
    OUTPUT.parent.mkdir(mode=0o700, exist_ok=True)
    OUTPUT.write_text(
        "\n".join(f"{email}={value}" for email, value in user_passwords.items()) + "\n"
    )
    OUTPUT.chmod(0o600)
    print(f"Keycloak resources configured; temporary user passwords saved to {OUTPUT} (mode 0600).")


if __name__ == "__main__":
    main()
