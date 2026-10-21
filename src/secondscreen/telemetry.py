"""OpenTelemetry for the agents, exported to Azure Monitor (App Insights).

Microsoft Agent Framework emits GenAI spans for every agent run, model call and
workflow step. Connect the App Insights resource to the Foundry project (Foundry
portal > your project > Tracing) and the traces appear there.

Enabled when APPLICATIONINSIGHTS_CONNECTION_STRING is set. Prompt and response text is
only recorded when ENABLE_SENSITIVE_DATA=true.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
_done = False


def setup_tracing(service_name: str = "second-screen") -> bool:
    global _done
    if _done:
        return True
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        return False
    try:
        from agent_framework.observability import configure_otel_providers
        from azure.monitor.opentelemetry.exporter import (AzureMonitorLogExporter, AzureMonitorMetricExporter,
                                                          AzureMonitorTraceExporter)
    except ImportError as e:  # tracing is optional
        log.warning("Tracing not enabled (%s). pip install azure-monitor-opentelemetry-exporter", e)
        return False
    configure_otel_providers(
        service_name=service_name,
        exporters=[AzureMonitorTraceExporter(connection_string=conn),
                   AzureMonitorMetricExporter(connection_string=conn),
                   AzureMonitorLogExporter(connection_string=conn)],
        enable_sensitive_data=os.environ.get("ENABLE_SENSITIVE_DATA", "").lower() == "true",
    )
    _done = True
    log.info("Tracing to Azure Monitor enabled")
    return True
