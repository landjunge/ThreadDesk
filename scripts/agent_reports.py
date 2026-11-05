#!/usr/bin/env python3
"""Run against the installed ThreadDesk API; no daemon/desktop restart required."""
import argparse
import importlib.util
import json
import time
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore

spec = importlib.util.spec_from_file_location('bigplan_reports', Path(__file__).resolve().parents[1] / 'src/threaddesk/services/agent_reports.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    report = sub.add_parser('report')
    for field in ('instance', 'agent', 'report-id', 'status', 'done', 'working', 'next'):
        report.add_argument('--' + field, required=True)
    report.add_argument('--blocker', default='')
    sub.add_parser('overview')
    sub.add_parser('refresh')
    watch = sub.add_parser('watch')
    watch.add_argument('--interval', type=int, default=60)
    args = parser.parse_args()
    reports = module.AgentReports(ThreadService(JsonStore(args.workspace), bus=module.ReportEventBus()))
    if args.action == 'report':
        print(json.dumps(reports.report(args.instance, args.agent, args.report_id,
            args.status, args.done, args.working, args.next, args.blocker), ensure_ascii=False))
    elif args.action == 'overview':
        print(json.dumps(reports.snapshot(), ensure_ascii=False, indent=2))
    elif args.action == 'refresh':
        print(reports.refresh())
    else:
        if args.interval < 10:
            parser.error('interval must be at least 10 seconds')
        while True:
            reports.refresh()
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
