"""Tests for /metrics Prometheus endpoint in TransportManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from apcore_mcp.server.transport import TransportManager

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _make_collector(export_text: str = "") -> MagicMock:
    """Create a mock MetricsCollector with a configurable export_prometheus() return."""
    collector = MagicMock()
    collector.export_prometheus.return_value = export_text
    return collector


# ---------------------------------------------------------------------------
# _build_metrics_response tests
# ---------------------------------------------------------------------------


class TestBuildMetricsResponse:
    """Tests for TransportManager._build_metrics_response."""

    def test_returns_404_when_no_collector(self) -> None:
        """Without a metrics collector, /metrics returns 404."""
        tm = TransportManager(metrics_collector=None)
        response = tm._build_metrics_response()
        assert response.status_code == 404

    def test_returns_200_with_collector(self) -> None:
        """With a metrics collector, /metrics returns 200."""
        collector = _make_collector("# HELP fake_counter A fake counter\n")
        tm = TransportManager(metrics_collector=collector)
        response = tm._build_metrics_response()
        assert response.status_code == 200

    def test_content_type_is_prometheus(self) -> None:
        """Response Content-Type matches Prometheus exposition format."""
        collector = _make_collector("# TYPE m counter\nm 1\n")
        tm = TransportManager(metrics_collector=collector)
        response = tm._build_metrics_response()
        assert response.media_type == PROMETHEUS_CONTENT_TYPE

    def test_body_matches_export_prometheus(self) -> None:
        """Response body is the exact output of export_prometheus()."""
        expected = '# HELP c desc\n# TYPE c counter\nc{module_id="a"} 5\n'
        collector = _make_collector(expected)
        tm = TransportManager(metrics_collector=collector)
        response = tm._build_metrics_response()
        assert bytes(response.body).decode() == expected

    def test_empty_export_returns_200(self) -> None:
        """An empty Prometheus export still returns 200 (collector is present)."""
        collector = _make_collector("")
        tm = TransportManager(metrics_collector=collector)
        response = tm._build_metrics_response()
        assert response.status_code == 200
        assert bytes(response.body).decode() == ""

    def test_export_prometheus_called_once(self) -> None:
        """export_prometheus() is called exactly once per request."""
        collector = _make_collector("data\n")
        tm = TransportManager(metrics_collector=collector)
        tm._build_metrics_response()
        collector.export_prometheus.assert_called_once()


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestTransportManagerMetricsCollector:
    """Tests for TransportManager metrics_collector parameter."""

    def test_default_metrics_collector_is_none(self) -> None:
        """TransportManager without metrics_collector defaults to None."""
        tm = TransportManager()
        assert tm._metrics_collector is None

    def test_metrics_collector_stored(self) -> None:
        """TransportManager stores the provided metrics_collector."""
        collector = _make_collector()
        tm = TransportManager(metrics_collector=collector)
        assert tm._metrics_collector is collector
