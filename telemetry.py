"""Conservative interpretation of received fields, without motion or pose inference."""
import base64
import json
import math

# Units describe the inspected WAVE_ROVER_V0.9 reference, not identified installed firmware.
FIELDS = {
    'v': ('V (reference)', 'measured', 'Supply voltage; calibration and firmware unverified'),
    'L': ('normalized PWM (reference WAVE mode)', 'commanded', 'Not measured wheel speed'),
    'R': ('normalized PWM (reference WAVE mode)', 'commanded', 'Not measured wheel speed'),
    'r': ('degrees (reference)', 'estimated', 'Fused orientation; sensor/body axes unregistered'),
    'p': ('degrees (reference)', 'estimated', 'Fused orientation; sensor/body axes unregistered'),
    'y': ('degrees only if orientation response', 'estimated', 'Ambiguous in arm module mode; never chamber Y'),
    **{k: ('raw native units; scale unverified', 'measured', 'No SI conversion until installed firmware scale is verified')
       for k in ('ax','ay','az','gx','gy','gz','mx','my','mz')},
    'current_mA': ('unverified', 'unknown', 'Reference computes current internally but does not expose this field in T:130/126'),
    'power_mW': ('unverified', 'unknown', 'Reference computes power internally but does not expose this field in T:130/126'),
    'temp': ('unverified', 'unknown', 'Reference includes a variable not demonstrably updated; not validated temperature'),
}


def decode_response(raw):
    text = raw.decode('utf-8', errors='replace')
    try:
        def finite_number(value):
            result=float(value)
            if not math.isfinite(result):raise ValueError('Non-finite JSON number')
            return result
        data = json.loads(text, parse_float=finite_number, parse_int=finite_number,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if data is None:
            return dict(raw_text=text, raw_base64=base64.b64encode(raw).decode(), parsed=None,
                        parse_error=None, response_note='JSON null: no feedback supplied; not a motor acknowledgement')
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        return dict(raw_text=text, raw_base64=base64.b64encode(raw).decode(), parsed=data, parse_error=None)
    except (ValueError, RecursionError) as error:
        return dict(raw_text=text, raw_base64=base64.b64encode(raw).decode(), parsed=None, parse_error=str(error))


class Telemetry:
    def __init__(self, clock):
        self.clock = clock
        self.fields = {}
        self.last_response = None
        self.fault = None

    def receive(self, response):
        now = self.clock()
        self.last_response = now
        self.fault = response.get('parse_error')
        data = response.get('parsed') or {}
        for key, value in data.items():
            if key == 'T':
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                continue
            previous = self.fields.get(key)
            self.fields[key] = dict(value=value, received=now,
                                   first=previous['first'] if previous else now,
                                   count=previous['count'] + 1 if previous else 1,
                                   changed=now if not previous or previous['value'] != value else previous['changed'],
                                   response_type=data.get('T'))

    def status(self):
        now = self.clock()
        rows = []
        for name in dict.fromkeys([*FIELDS, *self.fields]):
            unit, kind, limitation = FIELDS.get(name, ('unknown', 'unknown', 'Unrecognized field; raw value retained without interpretation'))
            record = self.fields.get(name)
            age = None if record is None else max(0, now-record['received'])
            span = record['received'] - record['first'] if record else 0
            rows.append(dict(field=name, units=unit, kind=kind, limitations=limitation,
                             support='observed numeric field; semantics unverified' if record else 'not observed / unavailable in this capture',
                             value=record['value'] if record else None,
                             response_type=record['response_type'] if record else None,
                             receive_age_s=age, receive_status='missing' if age is None else 'stale' if age > 2 else 'recent response',
                             observed_receive_hz=(record['count']-1)/span if span > 0 else None,
                             last_value_change_age_s=max(0, now-record['changed']) if record else None,
                             sensor_update_hz=None, sensor_sample_age_s=None,
                             freshness='Sensor acquisition time unknown; repeated replies do not prove fresh measurements'))
        return dict(fields=rows, fault=self.fault, firmware_identified=False,
                    note='No measured X/Y, odometry, wheel speed, lift height or airflow acquisition. Response receipt is not a command acknowledgement.')
