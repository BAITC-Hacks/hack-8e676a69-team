"""Weather-only ticket inference; no NVIDIA text-generation calls."""
from inference.forecast import ForecastPipeline


def build_pipelines(**kwargs):
    return {"forecast": ForecastPipeline(**kwargs)}
