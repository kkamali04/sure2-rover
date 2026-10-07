"""Manual calibration records and a NON-EXECUTING timed-route draft.

No transport, motor writes, position integration, or hardware execution lives here.
"""
import copy
import math
import statistics
from rover_test import validate_plan

DIRECTIONS = ('forward', 'reverse', 'left', 'right')


def finite(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number from {low} to {high}')
    return float(value)


def text(value, name, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{name} is required (1..{maximum} characters)')
    return value.strip()


def trial(payload, records, timestamp):
    keys = {'action', 'direction', 'pwm', 'duration_s', 'displacement', 'stop_distance_mm',
            'surface', 'configuration', 'evidence', 'duration_source', 'notes'}
    if set(payload) != keys:
        raise ValueError('Missing or unexpected calibration fields')
    if len(records) >= 500:
        raise ValueError('Calibration trial limit reached; start a new session')
    direction = payload['direction']
    if direction not in DIRECTIONS:
        raise ValueError('Choose forward, reverse, left or right')
    evidence = payload['evidence']
    if evidence not in ('software_example', 'physical_manual'):
        raise ValueError('Choose software example or physical manual measurement')
    source = payload['duration_source']
    if source not in ('stopwatch_video', 'command_timestamps'):
        raise ValueError('State how the drive interval was timed')
    result = dict(id=len(records)+1, time=timestamp, direction=direction,
                  pwm=finite(payload['pwm'], 'PWM', .05, .25),
                  duration_s=finite(payload['duration_s'], 'Drive interval (s)', .05, 120),
                  displacement=finite(payload['displacement'], 'Measured displacement', 0, 10000),
                  units='deg' if direction in ('left', 'right') else 'mm',
                  surface=text(payload['surface'], 'Surface'),
                  configuration=text(payload['configuration'], 'Rover/load/battery condition'),
                  evidence=evidence, duration_source=source,
                  notes=text(payload['notes'], 'Measurement method/notes', 2000),
                  measured_by_software=False)
    result['stop_distance_mm'] = None if payload['stop_distance_mm'] is None else finite(
        payload['stop_distance_mm'], 'Release-to-rest travel (mm)', 0, 10000)
    # This is displacement divided by the entered command interval, including startup/coast effects.
    # It is an empirical estimate, not measured instantaneous wheel speed.
    result['effective_rate'] = result['displacement'] / result['duration_s']
    return result


def summary(records):
    groups = {}
    for row in records:
        key = tuple(row[k] for k in ('direction', 'pwm', 'surface', 'configuration', 'evidence', 'duration_source'))
        groups.setdefault(key, []).append(row)
    result = []
    for key, rows in groups.items():
        rates = [r['effective_rate'] for r in rows]
        result.append(dict(zip(('direction', 'pwm', 'surface', 'configuration', 'evidence', 'duration_source'), key),
                           count=len(rows), mean_effective_rate=statistics.mean(rates),
                           sample_sd=statistics.stdev(rates) if len(rates)>1 else None,
                           units=rows[0]['units']+'/s', trial_ids=[r['id'] for r in rows]))
    return result


def compile_draft(plan, records, profile):
    if not plan:
        raise ValueError('Load a planner design first')
    if not isinstance(profile, dict) or set(profile) != {'pwm', 'surface', 'configuration', 'evidence', 'duration_source'}:
        raise ValueError('Select one complete calibration condition')
    profile = dict(profile, pwm=finite(profile['pwm'], 'PWM', .05, .25),
                   surface=text(profile['surface'], 'Surface'),
                   configuration=text(profile['configuration'], 'Rover/load/battery condition'))
    if profile['evidence'] not in ('software_example', 'physical_manual') or profile['duration_source'] not in ('stopwatch_video', 'command_timestamps'):
        raise ValueError('Select valid evidence and timing methods')
    checked = validate_plan(plan)
    if plan['motion']['heading_axis'] != 'route':
        raise ValueError('Use a route-heading plan exported by the current 2D planner')
    groups = {g['direction']:g for g in summary(records) if all(g[k] == v for k,v in profile.items())}
    steps, used = [], set()

    def move(direction, amount, station, **details):
        group = groups.get(direction)
        if not group or group['count'] < 3 or group['mean_effective_rate'] <= 0:
            raise ValueError(f'Need at least 3 non-stalled {direction} trials at the same PWM, surface, load and timing method')
        rows = [r for r in records if r['id'] in group['trial_ids']]
        if any(r['displacement'] <= 0 for r in rows):
            raise ValueError(f'{direction} includes a stalled trial; resolve the condition and record a new configuration')
        duration = amount/group['mean_effective_rate']
        if not math.isfinite(duration) or duration > 3600:
            raise ValueError('Estimated leg duration is too large; review calibration')
        used.update(group['trial_ids'])
        steps.append(dict(kind='estimated_motion', direction=direction, station=station,
                          target_displacement=amount, units=rows[0]['units'], estimated_seconds=duration,
                          calibration_trial_ids=group['trial_ids'],
                          extrapolated=not min(r['displacement'] for r in rows) <= amount <= max(r['displacement'] for r in rows),
                          **details))

    for index, station in enumerate(plan['stations']):
        pose = checked['route_preview'][index]
        if abs(pose['turn_deg']) > .01:
            move('left' if pose['turn_deg'] > 0 else 'right', abs(pose['turn_deg']), station['id'])
        for target in (s for s in checked['schedule'] if s['station'] == station['id']):
            steps.append(dict(kind='manual_position_and_height_check', target=copy.deepcopy(target),
                              sensor_measurement_taken=False))
        steps.append(dict(kind='manual_lift_park', station=station['id'], commanded=False))
        if index+1 < len(plan['stations']):
            following = plan['stations'][index+1]
            distance = math.hypot(following['x_mm']-station['x_mm'], following['y_mm']-station['y_mm'])
            move('reverse' if pose['reverse'] else 'forward', distance, station['id'],
                 destination=following['id'], target_x_mm=following['x_mm'], target_y_mm=following['y_mm'])
    return dict(schema='sure2.timed-route-draft.v1', hardware_execution_enabled=False,
                status='PRELIMINARY NON-EXECUTING DRAFT', calibration_profile=copy.deepcopy(profile),
                calibration_trials=[copy.deepcopy(r) for r in records if r['id'] in used],
                plan=copy.deepcopy(plan), steps=steps,
                estimated_rover_motion_seconds=sum(s.get('estimated_seconds',0) for s in steps),
                stationary_seconds=checked['acquisition_seconds'],
                measured_position=None, sensor_measurements=[],
                limitations=['No route executor is implemented; this file sends no commands.',
                             'X/Y are targets, not measured position. Timing is open-loop estimation.',
                             'Startup, battery, load, surface, stopping drift and wheel slip change travel.',
                             'Out-of-range distances/angles are flagged as extrapolation; test them separately.',
                             'Lift positioning/parking require manual work; no lift interface exists.',
                             'Dwell is elapsed time, not sensor acquisition. A 5 mm tolerance is unverified.'])
