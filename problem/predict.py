"""Inference from one CSV; no training data or persistent state required."""
import argparse
import json
from pathlib import Path
import pandas as pd
from forecasting import predict_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path(__file__).parent / "models_weather_context_no_power")
    parser.add_argument("--origin", help="First forecast hour in source/site time; required with future weather")
    parser.add_argument("--model", choices=["both", "catboost", "sarimax"])
    parser.add_argument("--weather-source", choices=["recorded_oracle", "forecast"],
                        help="Required for a model using supplied future weather")
    args = parser.parse_args()
    origin = pd.Timestamp(args.origin) if args.origin else None
    manifests = sorted(args.model_dir.glob("turbine_*/metadata.json"))
    if not manifests:
        parser.error(f"No model metadata found in {args.model_dir}")
    metadata = json.loads(manifests[0].read_text())
    if metadata.get("strategy") in ("pooled_direct_with_future_weather", "weather_context_no_power"):
        if origin is None or args.weather_source is None:
            parser.error("Weather-aware inference requires --origin and --weather-source")
        if args.model not in (None, "catboost"):
            parser.error("This bundle contains CatBoost only; select a legacy bundle for SARIMAX")
        if metadata['strategy'] == 'weather_context_no_power':
            from weather_context_forecasting import predict_csv as predict_weather
        else:
            from weather_forecasting import predict_csv as predict_weather
        prediction = predict_weather(args.input, args.model_dir, origin, args.weather_source)
        print("CAUTION: this model was trained on recorded weather, not archived weather forecasts.")
    else:
        prediction = predict_csv(args.input, args.model_dir, origin, args.model or "both")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    prediction.to_csv(args.output, index=False)
    print(f"Saved {len(prediction)} predictions to {args.output}")


if __name__ == "__main__":
    main()
