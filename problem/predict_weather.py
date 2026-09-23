"""Forecast 48h from one historical + future-weather CSV; never accesses network."""
import argparse
from pathlib import Path

from weather_context_forecasting import predict_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--origin', required=True, help='First forecast hour in source/site time')
    parser.add_argument('--weather-source', choices=['recorded_oracle', 'forecast'], required=True)
    parser.add_argument('--model-dir', type=Path, default=Path(__file__).resolve().parent / 'models_weather_context_no_power')
    args = parser.parse_args()
    result = predict_csv(args.input, args.model_dir, args.origin, args.weather_source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f'Saved {len(result)} forecast rows to {args.output}')
    print('CAUTION: models were trained on recorded weather, not archived weather forecasts.')


if __name__ == '__main__':
    main()
