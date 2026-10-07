"""Manual survey records, never a positioning or motion controller."""
import math
import statistics
from rover_test import number


def trial_record(payload, plan, previous, timestamp):
    fields = {'action', 'station', 'trial', 'actual_x_mm', 'actual_y_mm',
              'heading_deg', 'approach', 'observed_dwell_s', 'uncertainty_mm',
              'notes', 'evidence'}
    if set(payload) != fields:
        raise ValueError('Unexpected or missing station trial fields')
    if not plan:
        raise ValueError('Import a plan first')
    station = next((s for s in plan['stations'] if s['id'] == payload['station']), None)
    if not station:
        raise ValueError('Unknown station')
    trial = payload['trial']
    if type(trial) is not int or not 1 <= trial <= 10000:
        raise ValueError('Trial must be an integer from 1 to 10000')
    evidence = payload['evidence']
    if evidence not in ('physical_manual', 'software_example'):
        raise ValueError('Select physical manual measurement or software example')
    if any(r['station'] == station['id'] and r['trial'] == trial and r['evidence'] == evidence for r in previous):
        raise ValueError('This station/trial already exists; use the next trial number')
    if len(previous) >= 1000:
        raise ValueError('Session trial limit reached')
    approach = payload['approach']
    if approach not in ('+X', '-X', '+Y', '-Y', 'other'):
        raise ValueError('Select the final approach direction')
    notes = payload['notes']
    if not isinstance(notes, str) or not 1 <= len(notes.strip()) <= 2000:
        raise ValueError('Describe your measuring tool, datum and load (or software example)')
    x = number(payload['actual_x_mm'], 'Actual X', -100000, 100000)
    y = number(payload['actual_y_mm'], 'Actual Y', -100000, 100000)
    heading = number(payload['heading_deg'], 'Measured heading', -180, 180)
    uncertainty = number(payload['uncertainty_mm'], 'Measurement uncertainty', 0, 10000)
    dwell = payload['observed_dwell_s']
    if dwell is not None:
        dwell = number(dwell, 'Observed dwell', 0, 86400)
    dx, dy = x - station['x_mm'], y - station['y_mm']
    ox, oy = (plan['profile']['probe'][k] for k in ('offset_x_mm', 'offset_y_mm'))
    theta = math.radians(heading)
    px, py = x + ox * math.cos(theta) - oy * math.sin(theta), y + ox * math.sin(theta) + oy * math.cos(theta)
    return dict(time=timestamp, station=station['id'], trial=trial, evidence=evidence,
                target_x_mm=station['x_mm'], target_y_mm=station['y_mm'],
                actual_x_mm=x, actual_y_mm=y, error_x_mm=dx, error_y_mm=dy,
                radial_error_mm=math.hypot(dx, dy), heading_deg=heading,
                approach=approach, uncertainty_mm=uncertainty, notes=notes,
                planned_dwell_s=station['dwell_s'], observed_dwell_s=dwell,
                sensor_measurement_taken=False, profile_measured=plan['profile'].get('measured') is True,
                inferred_probe_x_mm=px, inferred_probe_y_mm=py,
                inferred_probe_error_mm=math.hypot(px-station['x_mm']-ox, py-station['y_mm']-oy),
                probe_position_source='Rigid-offset estimate from manually entered center and heading; not an independent probe measurement')


def summarize(records):
    groups = {}
    for record in records:
        key = (record['station'], record['approach'], record['evidence'])
        groups.setdefault(key, []).append(record)
    summary = []
    for (station, approach, evidence), rows in groups.items():
        x, y = ([r[k] for r in rows] for k in ('error_x_mm', 'error_y_mm'))
        n = len(rows)
        summary.append(dict(station=station, approach=approach, evidence=evidence, n=n,
                            bias_x_mm=statistics.mean(x), bias_y_mm=statistics.mean(y),
                            sample_sd_x_mm=statistics.stdev(x) if n > 1 else None,
                            sample_sd_y_mm=statistics.stdev(y) if n > 1 else None,
                            radial_rms_error_mm=math.sqrt(sum(r['radial_error_mm']**2 for r in rows)/n),
                            maximum_error_mm=max(r['radial_error_mm'] for r in rows),
                            acceptance='Not assessed; tolerance and measurement method must be agreed'))
    return summary
