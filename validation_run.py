"""Persistent operator observations and design timers. Never writes to a rover."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from rover_test import validate_plan
from station_trials import trial_record, summarize
from session_storage import prune


def utc():
    return datetime.now(timezone.utc).isoformat()


class ValidationRun:
    def __init__(self, run_id, live, clock, emit, directory=None):
        self.clock, self.emit = clock, emit
        self.directory = Path(directory) if directory else None
        self.active = None
        self.data = dict(run_id=run_id, live=live, started_at=utc(),
                         observations=[], plan=None, schedule=[], samples=[], next_index=0, station_trials=[],
                         limits="No automatic navigation, lift control, sensor capture, or measured position. "
                                "Physical results are operator reports; timer completion is not a measurement.")
        self.save()

    def save(self):
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / 'validation.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.status(), indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(target)
            prune(self.directory.parent, self.directory, max_bytes=75_000_000)

    def status(self):
        result = copy.deepcopy(self.data)
        result['station_summary'] = summarize(self.data['station_trials'])
        result['timer'] = None
        if self.active:
            sample = self.data['schedule'][self.active['index']]
            elapsed = max(0, self.clock() - self.active['start'])
            phase = 'settle' if elapsed < sample['settle_s'] else 'dwell'
            end = sample['settle_s'] if phase == 'settle' else sample['settle_s'] + sample['dwell_s']
            result['timer'] = dict(index=self.active['index'], phase=phase,
                                   elapsed_s=elapsed, remaining_s=max(0, end-elapsed))
        result['saved_to'] = str(self.directory) if self.directory else None
        return result

    def tick(self):
        if not self.active:
            return
        sample = self.data['schedule'][self.active['index']]
        elapsed = self.clock() - self.active['start']
        if not self.active['dwell_logged'] and elapsed >= sample['settle_s']:
            self.active['dwell_logged'] = True
            self.emit('dwell_started', index=self.active['index'], planned_settle_s=sample['settle_s'], elapsed_s=elapsed)
        if elapsed >= sample['settle_s'] + sample['dwell_s']:
            record = dict(index=self.active['index'], target=sample,
                          arrival=self.active['arrival'], started_at=self.active['started_at'],
                          ended_at=utc(), elapsed_s=elapsed, result='timer_completed',
                          sensor_measurement_taken=False)
            self.data['samples'].append(record)
            self.data['next_index'] += 1
            self.active = None
            self.emit('sample_timer_completed', **record)
            self.save()

    def cancel(self, reason):
        if self.active:
            record = dict(index=self.active['index'], result='cancelled', reason=reason,
                          elapsed_s=self.clock()-self.active['start'], ended_at=utc())
            self.data['samples'].append(record)
            self.active = None
            self.emit('sample_timer_cancelled', **record)
            self.save()

    def action(self, payload, *, armed, neutral_pending, ready):
        if not isinstance(payload, dict):
            raise ValueError('Expected an object')
        action = payload.get('action')
        if action == 'ui_event' and set(payload) == {'action', 'message'}:
            message = payload['message']
            if not isinstance(message, str) or len(message) > 1000:
                raise ValueError('UI message must be text, at most 1000 characters')
            self.emit('ui_event', message=message)
        elif action == 'observation' and set(payload) == {'action', 'check', 'result', 'notes'}:
            check, notes, result = payload['check'], payload['notes'], payload['result']
            if not isinstance(check, str) or not 1 <= len(check) <= 100:
                raise ValueError('Check name must be 1..100 characters')
            if not isinstance(notes, str) or len(notes) > 2000 or result not in ('pass', 'fail', 'not_tested'):
                raise ValueError('Use pass, fail or not_tested and notes up to 2000 characters')
            if len(self.data['observations']) >= 1000:
                raise ValueError('Observation limit reached for this session')
            record = dict(time=utc(), check=check, result=result, notes=notes, evidence='operator_report')
            self.data['observations'].append(record)
            self.emit('operator_observation', **record)
            self.save()
        elif action == 'import_plan' and set(payload) == {'action', 'plan'}:
            if armed or self.active:
                raise ValueError('STOP and cancel any timer before importing a plan')
            if self.data['samples'] or self.data['station_trials']:
                raise ValueError('This session already has samples or station trials. Start a new session for another plan.')
            plan = payload['plan']
            checked = validate_plan(plan)
            if len(checked['schedule']) > 600 or any(s['settle_s'] > 3600 or s['dwell_s'] > 3600 for s in checked['schedule']):
                raise ValueError('Plan limit: 600 samples and 3600 seconds per timing phase')
            self.data.update(plan=copy.deepcopy(plan), schedule=checked['schedule'],
                             plan_warnings=checked['warnings'], next_index=0)
            self.emit('plan_imported', samples=len(checked['schedule']), stationary_seconds=checked['acquisition_seconds'])
            self.save()
        elif action == 'station_trial':
            if armed or neutral_pending or self.active:
                raise ValueError('STOP and wait for neutral before recording a station trial')
            record = trial_record(payload, self.data['plan'], self.data['station_trials'], utc())
            self.data['station_trials'].append(record)
            self.emit('manual_station_trial', **record)
            self.save()
        elif action == 'arrived' and set(payload) == {'action', 'index', 'confirmation', 'notes'}:
            if armed or neutral_pending or not ready or self.active:
                raise ValueError('STOP first; wait for neutral and a ready transport before starting a timer')
            index = payload['index']
            if type(index) is not int or index != self.data['next_index'] or not 0 <= index < len(self.data['schedule']):
                raise ValueError('Select the next unfinished sample')
            if payload['confirmation'] not in ('operator_verified', 'timing_only'):
                raise ValueError('Choose operator-verified arrival or timing-only rehearsal')
            notes = payload['notes']
            if not isinstance(notes, str) or not 1 <= len(notes.strip()) <= 2000:
                raise ValueError('Describe how arrival/height was checked, or why this is timing-only')
            arrival = dict(confirmation=payload['confirmation'], notes=notes,
                           evidence='operator_report', position_measured_by_software=False)
            self.active = dict(index=index, start=self.clock(), started_at=utc(),
                               arrival=arrival, dwell_logged=False)
            self.emit('sample_timer_started', index=index, target=self.data['schedule'][index], arrival=arrival)
            self.save()
        elif action == 'cancel_timer' and set(payload) == {'action'}:
            self.cancel('Cancelled by operator')
        else:
            raise ValueError('Unknown validation action or unexpected fields')
        return self.status()
