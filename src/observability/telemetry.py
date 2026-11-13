"""Export OpenTelemetry metrics to Azure Monitor when configured."""

import os

CONNECTION_STRING_ENV = "APPLICATIONINSIGHTS_CONNECTION_STRING"
_configured = False


def configure_telemetry() -> None:
    global _configured
    if _configured or not os.getenv(CONNECTION_STRING_ENV):
        return

    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor()
    _configured = True
