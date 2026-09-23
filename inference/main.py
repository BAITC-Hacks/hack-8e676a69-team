"""Standalone alternative to the backend's embedded ticket worker."""
import argparse
import logging
from pathlib import Path
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from back.config import Settings
from inference.forecast import ForecastPipeline
from inference.supervisor import Supervisor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=.5)
    parser.add_argument('--tickets-dir', type=Path)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--timezone')
    parser.add_argument('--env-file', type=Path, help='Use the same back/.env as the API')
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('--interval must be positive')
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    settings = Settings.from_env()
    settings.validate()
    pipeline = ForecastPipeline(args.model_dir or settings.inference_model_dir,
                                args.timezone or settings.turbine_timezone, settings.inference_threads)
    worker = Supervisor(pipeline, args.tickets_dir or settings.tickets_dir, settings.inference_workers)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Watching %s; no power inputs; hourly 48h output', worker.request_dir)
    try:
        while True:
            worker.run_once()
            if not args.watch:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
