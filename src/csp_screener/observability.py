from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TracingStatus:
    mode: str
    project_name: str
    provider: Any


def setup_tracing() -> TracingStatus:
    """Configure Arize when credentials exist, otherwise emit local OTel spans."""
    project_name = os.getenv("ARIZE_PROJECT_NAME", "csp-screener-capstone")
    space_id = os.getenv("ARIZE_SPACE_ID")
    api_key = os.getenv("ARIZE_API_KEY")

    if space_id and api_key:
        from arize.otel import register

        provider = register(
            space_id=space_id,
            api_key=api_key,
            project_name=project_name,
        )
        mode = "arize"
    else:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        mode = "local-console"

    from openinference.instrumentation.langchain import LangChainInstrumentor

    LangChainInstrumentor().instrument(tracer_provider=provider)
    return TracingStatus(mode=mode, project_name=project_name, provider=provider)
