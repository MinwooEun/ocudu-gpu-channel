#!/usr/bin/env python3
"""Append scheduler reporting only for the separate 90-second qualification."""
from pathlib import Path
import re
import sys


def configure(text):
    if re.search(r'^(metrics|remote_control):', text, re.M):
        raise ValueError('existing metrics configuration requires reconciliation')
    return text + '''
metrics:
  enable_json: true
  layers:
    enable_sched: true
    enable_sched_ue: true
  periodicity:
    du_report_period: 1000
remote_control:
  enabled: true
  bind_addr: 127.0.0.1
  port: 8001
'''


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(configure(path.read_text()))
