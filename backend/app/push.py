"""Web Push (VAPID). On iPhone this works once Camena is added to the home screen
(iOS 16.4+) and the owner taps "Enable notifications" inside the installed app.
"""

from __future__ import annotations

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from .db import DB, iso, utcnow

log = logging.getLogger("camena.push")
KEY = "vapid"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Push:
    def __init__(self, db: DB, contact: str):
        self.db = db
        self.contact = contact
        keys = db.get_json(KEY)
        if not keys:
            private = ec.generate_private_key(ec.SECP256R1())
            pem = private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
            public = private.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
            keys = {"private_pem": pem, "public": _b64url(public)}
            db.set_json(KEY, keys)
        self._vapid = Vapid.from_pem(keys["private_pem"].encode())
        self.public_key = keys["public"]

    def subscribe(self, subscription: dict) -> None:
        self.db.run(
            "INSERT INTO push_subscriptions(endpoint, body, created_at) VALUES(?,?,?) "
            "ON CONFLICT(endpoint) DO UPDATE SET body = excluded.body",
            (subscription["endpoint"], json.dumps(subscription), iso(utcnow())),
        )

    def count(self) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM push_subscriptions")["n"]

    def send(self, title: str, body: str, url: str = "./") -> int:
        """Send to every subscribed device; drops subscriptions the push service rejects."""
        payload = json.dumps({"title": title, "body": body[:240], "url": url})
        sent = 0
        for row in self.db.all("SELECT endpoint, body FROM push_subscriptions"):
            try:
                webpush(
                    subscription_info=json.loads(row["body"]),
                    data=payload,
                    vapid_private_key=self._vapid,
                    vapid_claims={"sub": self.contact},
                    ttl=3600,
                )
                sent += 1
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):
                    self.db.run("DELETE FROM push_subscriptions WHERE endpoint = ?", (row["endpoint"],))
                log.warning("push failed (%s): %s", status, e)
        return sent
