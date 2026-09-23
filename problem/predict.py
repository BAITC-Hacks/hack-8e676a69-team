"""Inference from one CSV; no training data or persistent state required."""
import argparse
from pathlib import Path
import pandas as pd
from forecasting import predict_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path(__file__).parent / "models_direct_missing")
    parser.add_argument("--origin", help="First forecast hour in source/site time; default max timestamp + 1h")
    parser.add_argument("--model", choices=["both", "catboost", "sarimax"], default="both")
    args = parser.parse_args()
    origin = pd.Timestamp(args.origin) if args.origin else None
    prediction = predict_csv(args.input, args.model_dir, origin, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    prediction.to_csv(args.output, index=False)
    print(f"Saved {len(prediction)} predictions to {args.output}")


if __name__ == "__main__":
    main()
