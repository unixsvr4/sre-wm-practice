import os

# Set before main.py is imported during test collection.
os.environ["OTLP_ENDPOINT"] = "http://localhost:4317"

# Replace BatchSpanProcessor with a no-op before main.py imports it.
# Without this, the real gRPC exporter triggers a ~30-second hang at test
# exit while trying to flush spans to a non-existent collector.
from unittest.mock import MagicMock
import opentelemetry.sdk.trace.export as _otel_export
_otel_export.BatchSpanProcessor = MagicMock(return_value=MagicMock())
