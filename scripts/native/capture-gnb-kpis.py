#!/usr/bin/env python3
"""Preserve 60 consecutive one-second scheduler reports after gateway ping."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web_ui'))
from server import WebSocketClient, GNB_METRICS_SUBSCRIBE, extract_ue_rows, is_scheduler_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    client = WebSocketClient('127.0.0.1', args.port, timeout=5)
    try:
        client.send_text(GNB_METRICS_SUBSCRIBE)
        with args.output.open('x') as stream:
            count = 0
            while count < 60:
                message = client.recv_message()
                if message is None:
                    raise RuntimeError('gNB closed before 60 scheduler reports')
                payload = json.loads(message)
                if not is_scheduler_report(payload):
                    continue
                rows = extract_ue_rows(payload)
                stream.write(json.dumps(dict(monotonic_seconds=time.monotonic(), rows=rows, payload=payload)) + '\n')
                stream.flush()
                count += 1
        print('event=cuda_kpi_capture result=pass reports=60', flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
