"""Interactive raised-wheel diagnostic. Preview by default, no automatic sequence."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from hardware_owner import HardwareOwner
from remote_controller import RoverHTTP
from rover_test import STOP, number
from telemetry_capture import capture
from session_storage import register, finish, EventLog

MOVES = {'w': (.1, .1), 's': (-.1, -.1), 'a': (-.1, .1), 'd': (.1, -.1),
         'left': (.1, 0.), 'right': (0., .1)}


def bounded_check(transport, key, log, sleep=time.sleep, clock=time.monotonic, *, pwm=.1, seconds=.25, dwell_s=0):
    """One selected .25-second host pulse; stop on exit, never retry movement."""
    if key not in MOVES:
        raise ValueError('Select w, s, a, d, left or right')
    pwm=number(pwm,'PWM',.05,.25)
    seconds=number(seconds,'Move interval',.02,1)
    dwell_s=number(dwell_s,'Stopped dwell',0,60)
    def send(command):
        log('command_attempt', command=command)
        try:
            response = transport.send(command)
            log('response', command=command, response=response)
        except BaseException as error:
            log('transport_fault', command=command, error=str(error))
            raise
    stop_errors = []
    try:
        send(dict(STOP))
        sleep(.1)
        left, right = MOVES[key]
        deadline = clock() + seconds
        send(dict(T=1, L=round(left*pwm/.1,8), R=round(right*pwm/.1,8)))
        sleep(max(0, deadline-clock()))
    finally:
        for _ in range(3):
            try:
                send(dict(STOP))
            except (Exception, KeyboardInterrupt) as error:
                stop_errors.append(str(error))
        if stop_errors:
            raise OSError('Neutral transmission failed. Use physical cutoff if wheels move. '+ '; '.join(stop_errors))
    if dwell_s:
        started=clock()
        log('stopped_dwell_started',planned_s=dwell_s,physical_stop_verified=False)
        sleep(dwell_s)
        log('stopped_dwell_completed',elapsed_s=clock()-started,sensor_measurement_taken=False)


def ask_observation(read=input):
    while True:
        observation=read('RESULT (not a movement key): pass / fail / unsure, plus wheel and stopping observations: ').strip()
        result=observation.split(' ',1)[0].lower()
        if result in ('pass','fail','unsure'):
            return result,observation[:2000]
        print('No movement sent. Enter pass, fail or unsure for the PREVIOUS check; movement keys are accepted at the next menu.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.4.1')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--pwm',type=float,default=.1)
    parser.add_argument('--pulse-seconds',type=float,default=.25)
    parser.add_argument('--dwell-seconds',type=float,default=0)
    args=parser.parse_args(argv)
    try:
        number(args.pwm,'PWM',.05,.25);number(args.pulse_seconds,'Move interval',.02,1);number(args.dwell_seconds,'Stopped dwell',0,60)
    except ValueError as error:parser.error(str(error))
    if not args.live:
        print(f'PREVIEW: initial read-only capture, then individually selected {args.pwm:g} PWM / {args.pulse_seconds:g}-second moves followed by {args.dwell_seconds:g} seconds stopped dwell. Open-loop timing, not distance or X/Y. No network connection without --live.')
        return 0
    print('Close all rover controllers. Raise ALL wheels and keep the physical cutoff accessible.')
    if input('Type RAISED when ready, or Enter to quit: ').strip() != 'RAISED':
        return 0
    try:
        owner=HardwareOwner()
    except OSError as error:
        print('CHECK NOT STARTED:',error)
        return 2
    folder=Path(__file__).parent/'test_runs'/('hardware-check-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    folder.mkdir(parents=True)
    transport=RoverHTTP(args.host)
    try:
        print('Reading status only for 10 seconds...')
        report=capture(transport, folder, seconds=10)
        register(folder, 'hardware_check')
        print('Observed fields:', ', '.join(f['field'] for f in report['fields'] if f['value'] is not None) or 'none')
        with EventLog(folder/'controller_log.jsonl') as log:
            log('operator_setup', wheels_raised_reported=True, target=args.host)
            log('test_parameters',pwm=args.pwm,pulse_seconds=args.pulse_seconds,dwell_seconds=args.dwell_seconds,position_source='unavailable')
            print(f'Each selected check: {args.pwm:g} PWM for {args.pulse_seconds:g} seconds, then neutral + {args.dwell_seconds:g} seconds dwell. Timing is host-side, not guaranteed wheel duration or distance.')
            print('w forward | s reverse | a pivot left | d pivot right | left left-side only | right right-side only | q quit')
            while True:
                key=input('Select one brief physical check (q quits): ').strip().lower()
                if key in ('q',''):
                    break
                if key not in MOVES:
                    print('Unknown selection; no command sent.');continue
                log('operator_selected_check', selection=key)
                try:
                    bounded_check(transport,key,log,pwm=args.pwm,seconds=args.pulse_seconds,dwell_s=args.dwell_seconds)
                except (Exception, KeyboardInterrupt) as error:
                    log('check_aborted',error=str(error));print('ABORTED:',error);return 1
                result,observation=ask_observation()
                log('operator_observation', check=key, result=result if result in ('pass','fail','unsure') else 'unsure', notes=observation,
                    evidence='operator_report', movement_measured_by_software=False)
                if result != 'pass':
                    print('Ending after failure/uncertainty. Keep the log for diagnosis; no further movement scheduled.');return 1
    finally:
        transport.close();owner.close();finish(folder);print('Saved:',folder)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
