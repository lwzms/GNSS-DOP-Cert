"""One receiver / epoch / satellite / header-declared signal per record.

All-empty signal groups are retained. RINEX event flags other than 0/1 fail.
No clock, phase, scale, or geometric correction is applied.
"""

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite

from gnss_toolbox.data.audit.rinex import Lines, read_header, read_satellite
from gnss_toolbox.data.audit.timing import NS, calendar_ns, format_calendar
from gnss_toolbox.data.schema import Constellation, GnssObservation, TimeScale

DATASET = 'UrbanNav'
SEQUENCE = 'UrbanNav-HK-Medium-Urban-1'
RECEIVER = 'hk_medium_file_ublox_f9p_splitter'
SYSTEMS = dict(zip('GRECJSI', (Constellation.GPS, Constellation.GLONASS,
    Constellation.GALILEO, Constellation.BEIDOU, Constellation.QZSS,
    Constellation.SBAS, Constellation.IRNSS)))
GPS_ORIGIN_NS = 315964800 * NS


def gps_calendar_ns(parts):
    result = calendar_ns(parts) - GPS_ORIGIN_NS
    if result < 0:
        raise ValueError('calendar predates GPS epoch')
    return result


def gps_ns_calendar(timestamp_ns):
    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise ValueError('nonnegative integer GPS nanoseconds required')
    return format_calendar(timestamp_ns + GPS_ORIGIN_NS)


@dataclass(frozen=True)
class GnssEpochMetadata:
    timestamp_ns: int
    time_scale: TimeScale
    epoch_flag: int
    reported_satellite_count: int
    receiver_clock_offset_s: str | None
    source_epoch_index: int
    receiver_id: str = RECEIVER


@dataclass(frozen=True)
class GnssSignalExtras:
    timestamp_ns: int
    receiver_id: str
    sv_id: str
    signal_code: str
    raw_s_value: str | None
    raw_s_observable_code: str | None
    s_unit_status: str = 'PROVISIONAL'
    phase_ssi: int | None = None
    code_ssi: int | None = None
    doppler_ssi: int | None = None
    s_ssi: int | None = None
    receiver_identity_confidence: str = 'PROVISIONAL'


def numeric(text):
    if not text:
        return None
    number = float(text.replace('D', 'E').replace('d', 'e'))
    if not isfinite(number):
        raise ValueError('nonfinite RINEX observation')
    return number


def indicator(text, limit):
    if not text.strip():
        return None
    if not text.isdigit() or not 0 <= int(text) <= limit:
        raise ValueError('invalid RINEX indicator')
    return int(text)


def observation_epochs(path):
    """Yield metadata and at most one epoch of lexical satellite records."""
    with path.open(encoding='ascii') as handle:
        lines = Lines(handle)
        header = read_header(lines)
        time = header['fields'].get('TIME OF FIRST OBS', [''])[0].split()
        if header['version'] != '3.03' or not time or time[-1] != 'GPS':
            raise ValueError('HK Medium requires explicit RINEX 3.03 / GPS')
        # A nontrivial scale header would require another reviewed mapping policy.
        # read_header intentionally selects known fields; check unsupported directives
        # in a bounded second header pass rather than silently accepting them.
        with path.open(encoding='ascii') as check:
            for line in check:
                label = line[60:].strip()
                if label == 'END OF HEADER':
                    break
                if label in ('SYS / SCALE FACTOR', 'SYS / DCBS APPLIED', 'SYS / PCVS APPLIED'):
                    raise ValueError('unsupported observation correction directive')
        index = 0
        while (line := lines.pop()) is not None:
            if not line.strip():
                continue
            parts = line[1:].split()
            if not line.startswith('>') or len(parts) not in (8, 9):
                raise ValueError('invalid epoch line')
            flag, count = int(parts[6]), int(parts[7])
            if flag not in (0, 1):
                raise ValueError('unsupported special epoch event')
            if count < 0 or count > 999:
                raise ValueError('invalid satellite count')
            clock = parts[8] if len(parts) == 9 else None
            if clock is not None and not Decimal(clock.replace('D', 'E')).is_finite():
                raise ValueError('nonfinite receiver clock offset')
            epoch = GnssEpochMetadata(gps_calendar_ns(parts[:6]), TimeScale.GPS, flag, count, clock, index)
            rows, seen = [], set()
            for _ in range(count):
                sv, payload = read_satellite(lines, header['observable_codes'])
                if sv in seen:
                    raise ValueError('duplicate satellite in epoch')
                seen.add(sv)
                cells = {}
                for i, code in enumerate(header['observable_codes'][sv[0]]):
                    cell = payload[i*16:(i+1)*16]
                    value = cell[:14].strip()
                    numeric(value)
                    cells[code] = (value or None, indicator(cell[14], 7), indicator(cell[15], 9))
                rows.append((sv, cells))
            yield epoch, rows
            index += 1


def stage_epoch(epoch, rows):
    week, tow_ns = divmod(epoch.timestamp_ns, 604800 * NS)
    for sv, cells in rows:
        for signal in dict.fromkeys(code[1:] for code in cells):
            c, l, d, s = [cells.get(k + signal, (None, None, None)) for k in 'CLDS']
            record = GnssObservation(dataset=DATASET, sequence=SEQUENCE,
                timestamp_ns=epoch.timestamp_ns, time_scale=TimeScale.GPS,
                receiver_id=RECEIVER, constellation=SYSTEMS[sv[0]], sv_id=sv,
                prn=int(sv[1:]), signal_code=signal, gps_week=week, tow_s=tow_ns / NS,
                pseudorange_m=numeric(c[0]), carrier_phase_cycles=numeric(l[0]),
                doppler_hz=numeric(d[0]), lli=l[1] if l[0] is not None else None)
            extras = GnssSignalExtras(epoch.timestamp_ns, RECEIVER, sv, signal,
                s[0], 'S' + signal if 'S' + signal in cells else None,
                phase_ssi=l[2], code_ssi=c[2], doppler_ssi=d[2], s_ssi=s[2])
            yield record, extras
