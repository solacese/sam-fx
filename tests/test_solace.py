import logging

from fx_regime.solace import SolaceBus


def test_topic_matching() -> None:
    assert SolaceBus._matches("fx/regime/*/change", "fx/regime/EURUSD/change")
    assert SolaceBus._matches("agent/fx-regime/>", "agent/fx-regime/result/detail")
    assert not SolaceBus._matches("fx/regime/*/change", "fx/market/EURUSD/price")


def test_malformed_payload_is_ignored(caplog) -> None:
    bus = SolaceBus("")
    received = []
    bus.subscribe("fx/regime/*/change", received.append)
    with caplog.at_level(logging.WARNING):
        bus._dispatch("fx/regime/EURUSD/change", "not-json")
    assert received == []
    assert "Ignoring malformed JSON" in caplog.text
