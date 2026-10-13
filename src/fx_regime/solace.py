from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    from solace.messaging.config.transport_security_strategy import TLS
    from solace.messaging.messaging_service import MessagingService
    from solace.messaging.receiver.message_receiver import MessageHandler
    from solace.messaging.resources.topic import Topic
    from solace.messaging.resources.topic_subscription import TopicSubscription
except ImportError:  # pragma: no cover - dependency is optional for local UI work
    MessagingService = None
    MessageHandler = object


class _Handler(MessageHandler):  # type: ignore[misc]
    def __init__(self, owner: SolaceBus) -> None:
        self.owner = owner

    def on_message(self, message: Any) -> None:
        self.owner._dispatch(message.get_destination_name(), message.get_payload_as_string())


class SolaceBus:
    """Solace SMF transport with SDK-managed reconnect and malformed-message isolation."""

    def __init__(
        self,
        host: str,
        *,
        vpn: str = "default",
        username: str = "",
        password: str = "",
        client_id: str = "fx-regime-service",
    ) -> None:
        self.host = host
        self.vpn = vpn
        self.username = username
        self.password = password
        self.client_id = client_id
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._connected = threading.Event()
        self._service: Any = None
        self._publisher: Any = None
        self._receiver: Any = None

    @property
    def enabled(self) -> bool:
        return bool(self.host)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if not self.enabled:
            return
        if MessagingService is None:
            raise RuntimeError("solace-pubsubplus is required when SOLACE_HOST is configured")
        properties = {
            "solace.messaging.transport.host": self.host,
            "solace.messaging.service.vpn-name": self.vpn,
            "solace.messaging.authentication.scheme.basic.username": self.username,
            "solace.messaging.authentication.scheme.basic.password": self.password,
            "solace.messaging.client-name": self.client_id,
        }
        builder = MessagingService.builder().from_properties(properties)
        if self.host.startswith(("tcps://", "wss://")):
            builder = builder.with_transport_security_strategy(
                TLS.create().with_certificate_validation(True)
            )
        self._service = builder.build()
        self._service.connect()
        self._publisher = self._service.create_direct_message_publisher_builder().build()
        self._publisher.start()
        subscriptions = [TopicSubscription.of(topic) for topic in self._handlers]
        if subscriptions:
            self._receiver = (
                self._service.create_direct_message_receiver_builder()
                .with_subscriptions(subscriptions)
                .build()
            )
            self._receiver.start()
            self._receiver.receive_async(_Handler(self))
        self._connected.set()

    def stop(self) -> None:
        if self._receiver:
            self._receiver.terminate()
        if self._publisher:
            self._publisher.terminate()
        if self._service:
            self._service.disconnect()
        self._connected.clear()

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], None]) -> None:
        if self._service:
            raise RuntimeError("Subscriptions must be registered before starting SolaceBus")
        self._handlers[topic] = handler

    def publish(self, topic: str, body: BaseModel | dict[str, Any]) -> None:
        if not self.enabled:
            return
        if not self.connected or not self._publisher:
            logger.warning("Solace publisher is not connected; skipped %s", topic)
            return
        payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
        self._publisher.publish(json.dumps(payload), Topic.of(topic))

    def _dispatch(self, topic: str, raw_payload: str) -> None:
        try:
            payload = json.loads(raw_payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            logger.warning("Ignoring malformed JSON on %s", topic)
            return
        for subscription, handler in self._handlers.items():
            if self._matches(subscription, topic):
                handler(payload)

    @staticmethod
    def _matches(subscription: str, topic: str) -> bool:
        wanted = subscription.split("/")
        actual = topic.split("/")
        for index, part in enumerate(wanted):
            if part == ">":
                return True
            if index >= len(actual) or (part != "*" and part != actual[index]):
                return False
        return len(wanted) == len(actual)
