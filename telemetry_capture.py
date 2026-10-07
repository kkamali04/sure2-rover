"""User-started read-only T:130 / T:126 HTTP capture. Default only previews."""
import argparse
import csv
import json
from pathlib import Path
import time
from datetime import datetime, timezone
from hardware_owner import HardwareOwner
from remote_controller import RoverHTTP
from telemetry import Telemetry
from session_storage import register, finish, EventLog


def capture(transport, directory, seconds=20, interval=.5):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    register(directory, 'telemetry')
    state = Telemetry(time.monotonic)
    started = time.monotonic()
    attempts = 0
    with EventLog(directory/'raw_responses.jsonl') as log:
        log('capture_started', commands=[{'T':130}, {'T':126}], note='Read-only requests; no neutral, arm, drive, firmware or configuration writes')
        try:
            transport.open()
            while time.monotonic()-started < seconds:
                command = {'T': 130 if attempts % 2 == 0 else 126}
                attempts += 1
                log('query', command=command)
                try:
                    response = transport.send(command)
                    state.receive(response)
                    log('response', command=command, **response)
                except Exception as error:
                    state.fault = str(error)
                    log('fault', command=command, error=str(error))
                time.sleep(min(interval, max(0, seconds-(time.monotonic()-started))))
        except KeyboardInterrupt:
            log('capture_interrupted')
        finally:
            transport.close()
            report = state.status()
            report.update(attempts=attempts, duration_s=time.monotonic()-started,
                          completed_at=datetime.now(timezone.utc).isoformat(),
                          note='Read-only capture ended. Freshness is evaluated at completed_at; data are historical afterward. Sensor update rate is unknown.')
            (directory/'telemetry_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            with (directory/'telemetry_fields.csv').open('w', newline='', encoding='utf-8') as file:
                writer=csv.DictWriter(file, fieldnames=list(report['fields'][0]));writer.writeheader();writer.writerows(report['fields'])
            log('capture_ended', attempts=attempts)
    finish(directory)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.4.1')
    parser.add_argument('--capture', action='store_true', help='Actually send read-only status queries; close controller first')
    parser.add_argument('--seconds', type=float, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 60:
        parser.error('Use 1..60 seconds')
    if not args.capture:
        print('PREVIEW ONLY: alternate T:130 base status and T:126 IMU reads. No network request. Add --capture after joining rover Wi-Fi with wheels raised and other control apps closed.')
        return 0
    try:
        owner = HardwareOwner()
    except OSError as error:
        print('TELEMETRY NOT STARTED:', error)
        return 2
    try:
        folder = Path(__file__).parent/'test_runs'/('telemetry-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        report=capture(RoverHTTP(args.host), folder, args.seconds)
        print('Capture saved:', folder)
        observed = [r['field'] for r in report['fields'] if r['value'] is not None]
        print('Observed fields:', ', '.join(observed) or 'NONE; inspect raw responses and faults')
        return 0 if observed else 1
    finally:
        owner.close()


if __name__ == '__main__':
    raise SystemExit(main())
