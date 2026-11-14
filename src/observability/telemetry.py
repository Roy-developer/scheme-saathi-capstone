"""Export OpenTelemetry metrics to Azure Monitor when configured."""

import os

CONNECTION_STRING_ENV = "APPLICATIONINSIGHTS_CONNECTION_STRING"
RESOURCE_ATTRIBUTES_ENV = "OTEL_RESOURCE_ATTRIBUTES"
APP_VERSION_ENV = "APP_VERSION"
DEFAULT_SERVICE_NAME = "scheme-saathi-api"
_configured = False


def _with_default_resource_attributes() -> None:
    """Label telemetry with the deployed version and a service name.

    Every deploy already sets APP_VERSION to the image tag, so the telemetry
    label follows each deploy without a manual setting that could go stale.
    Values set explicitly in OTEL_RESOURCE_ATTRIBUTES are never overridden.
    """

    attributes: dict[str, str] = {}
    for pair in os.getenv(RESOURCE_ATTRIBUTES_ENV, "").split(","):
        key, separator, value = pair.partition("=")
        if separator and key.strip():
            attributes[key.strip()] = value.strip()
    version = os.getenv(APP_VERSION_ENV, "").strip()
    if version and "service.version" not in attributes:
        attributes["service.version"] = version
    attributes.setdefault("service.name", DEFAULT_SERVICE_NAME)
    os.environ[RESOURCE_ATTRIBUTES_ENV] = ",".join(
        f"{key}={value}" for key, value in attributes.items()
    )


def configure_telemetry() -> None:
    global _configured
    if _configured or not os.getenv(CONNECTION_STRING_ENV):
        return

    from azure.monitor.opentelemetry import configure_azure_monitor

    _with_default_resource_attributes()
    configure_azure_monitor()
    _configured = True
