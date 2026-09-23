import argparse
import time

try:
    from .pipelines import build_pipelines
    from .supervisor import Supervisor
except ImportError:  # Allows `python app/main.py`.
    from pipelines import build_pipelines
    from supervisor import Supervisor


def main():
    parser = argparse.ArgumentParser(description="Process request subfolders.")
    parser.add_argument("--watch", action="store_true", help="keep polling for new requests")
    parser.add_argument("--interval", type=float, default=1, help="watch polling interval in seconds")
    args = parser.parse_args()
    supervisor = Supervisor(build_pipelines())
    while True:
        completed = supervisor.run_once()
        for future in completed:
            request_id, status = future.result()
            print(f"{request_id}: {status}")
        if not args.watch:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
