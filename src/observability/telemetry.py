"""Export OpenTelemetry signals to Azure Monitor when it is configured."""

import os

CONNECTION_STRING_ENV = "APPLICATIONINSIGHTS_CONNECTION_STRING"


def configure_telemetry() -> None:
    if not os.getenv(CONNECTION_STRING_ENV):
        return

    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor()
