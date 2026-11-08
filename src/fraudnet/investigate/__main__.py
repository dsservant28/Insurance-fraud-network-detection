"""Command line: python -m fraudnet.investigate --data data/output {demo,list,verify,export FILE}"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fraudnet.investigate.demo import DemoClock, seed_demo
from fraudnet.investigate.schema import connect
from fraudnet.investigate.workflow import Workflow, export_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigation cases in fraudnet.db.")
    parser.add_argument("--data", type=Path, default=Path("data/output"))
    parser.add_argument("command", choices=("demo", "list", "verify", "export"))
    parser.add_argument("file", nargs="?", type=Path, help="output file for export")
    args = parser.parse_args()

    connection = connect(args.data / "fraudnet.db")
    if args.command == "demo":
        opened = seed_demo(Workflow(connection, clock=DemoClock()))
        print(f"Demo cases opened: {', '.join(opened) if opened else 'none (cases already exist)'}")
    workflow = Workflow(connection)
    if args.command in ("demo", "list"):
        for case in workflow.cases():
            print(f"{case['investigation_id']} {case['trigger_type']:<14} {case['priority']:<8} "
                  f"{case['current_status']:<16} {case['network_id'] or case['exception_id']}")
    elif args.command == "verify":
        for case in workflow.cases():
            chain = workflow.verify_chain(case["investigation_id"])
            print(f"{case['investigation_id']}: {'chain intact' if chain['intact'] else 'BROKEN at seq ' + str(chain['broken_at_seq'])}")
    elif args.command == "export":
        target = args.file or args.data / "investigations.json"
        target.write_text(json.dumps(export_history(workflow), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"History written to {target}")
    connection.close()


if __name__ == "__main__":
    main()
