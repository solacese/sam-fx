#!/usr/bin/env python3
"""Obtain a short-lived Agent Mesh login token without persisting or logging it."""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

NAMESPACE = "sam-fx"
TOKEN_URL = "https://id.fx.sol-se-emea.com/realms/fx/protocol/openid-connect/token"


def main() -> None:
    users = dict(
        line.split("=", 1)
        for line in Path(".credentials/keycloak-users.txt").read_text().splitlines()
        if "=" in line
    )
    secret = json.loads(
        subprocess.check_output(
            ["kubectl", "get", "secret", "fx-oauth", "-n", NAMESPACE, "-o", "json"],
            text=True,
        )
    )
    client_secret = base64.b64decode(secret["data"]["client-secret"]).decode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(
            {
                "client_id": "sam-webui",
                "client_secret": client_secret,
                "grant_type": "password",
                "username": "raphael.caillon@solace.com",
                "password": users["raphael.caillon@solace.com"],
                "scope": "openid profile email",
            }
        ).encode(),
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        print(json.load(response)["access_token"])


if __name__ == "__main__":
    main()
