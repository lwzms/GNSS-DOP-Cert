"""Canonical data contracts, version 0.1.0. No parsers or estimators.

Research-only ReferenceState lives in gnss_toolbox.evaluation.reference.
See docs/data_schema.md for epochs, frames, signs and provenance.
"""

from dataclasses import dataclass, fields
from enum import Enum
from math import isfinite
import re
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

SCHEMA_VERSION = "0.1.0"
Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


class TimeScale(str, Enum):
    GPS = "GPS"
    UTC = "UTC"
    UNIX = "UNIX"


class Constellation(str, Enum):
    GPS = "GPS"
    GLONASS = "GLONASS"
    GALILEO = "GALILEO"
    BEIDOU = "BEIDOU"
    QZSS = "QZSS"
    SBAS = "SBAS"
    IRNSS = "IRNSS"


def _matches(value: object, annotation: object) -> bool:
    """Check the small annotation vocabulary used by these records."""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return any(_matches(value, arg) for arg in args)
    if origin is Literal:
        return value in args and type(value) is type(args[0])
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_matches(item, args[0]) for item in value)
        return len(value) == len(args) and all(
            _matches(item, kind) for item, kind in zip(value, args)
        )
    if annotation is float:
        return type(value) in (int, float) and isfinite(value)
    if annotation in (int, bool, str):
        return type(value) is annotation
    return isinstance(value, annotation)


@dataclass(frozen=True, slots=True, kw_only=True)
class Record:
    dataset: str
    sequence: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        annotations = get_type_hints(type(self))
        for item in fields(self):
            value = getattr(self, item.name)
            if not _matches(value, annotations[item.name]):
                raise TypeError(f"{item.name}: invalid type, shape or non-finite value")
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"{item.name}: empty strings are not canonical")
            if item.name.endswith("timestamp_ns") and value is not None:
                if not -(2**63) <= value < 2**63:
                    raise ValueError(f"{item.name}: outside signed int64 range")
            if "_std_" in item.name and value is not None:
                values = value if isinstance(value, tuple) else (value,)
                if any(component < 0 for component in values):
                    raise ValueError(f"{item.name}: negative standard deviation")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedRecord(Record):
    timestamp_ns: int
    time_scale: TimeScale


@dataclass(frozen=True, slots=True, kw_only=True)
class GnssObservation(TimedRecord):
    receiver_id: str
    constellation: Constellation
    sv_id: str
    prn: int
    signal_code: str
    gps_week: int | None = None
    tow_s: float | None = None
    carrier_frequency_hz: float | None = None
    glonass_frequency_slot: int | None = None
    pseudorange_m: float | None = None
    pseudorange_std_m: float | None = None
    carrier_phase_cycles: float | None = None
    carrier_phase_std_cycles: float | None = None
    doppler_hz: float | None = None
    doppler_std_hz: float | None = None
    cn0_dbhz: float | None = None
    lli: int | None = None
    tracking_status: str | None = None

    def __post_init__(self) -> None:
        super(GnssObservation, self).__post_init__()
        if not re.fullmatch(r"[1-9][A-Z]", self.signal_code):
            raise ValueError("signal_code must be a RINEX 3/4 band+tracking code, e.g. 1C")
        if self.prn <= 0:
            raise ValueError("prn must be positive")
        if (self.gps_week is None) != (self.tow_s is None):
            raise ValueError("gps_week and tow_s must be supplied together")
        if self.gps_week is not None and (self.gps_week < 0 or not 0 <= self.tow_s < 604800):
            raise ValueError("invalid GPS week or time of week")
        if self.carrier_frequency_hz is not None and self.carrier_frequency_hz <= 0:
            raise ValueError("carrier frequency must be positive")
        if self.glonass_frequency_slot is not None:
            if self.constellation is not Constellation.GLONASS:
                raise ValueError("frequency slot applies only to GLONASS")
            if not -7 <= self.glonass_frequency_slot <= 6:
                raise ValueError("GLONASS FDMA frequency slot must be in [-7, 6]")
        if self.lli is not None and not 0 <= self.lli <= 7:
            raise ValueError("RINEX LLI must be in [0, 7]")
        for quantity, uncertainty in (
            (self.pseudorange_m, self.pseudorange_std_m),
            (self.carrier_phase_cycles, self.carrier_phase_std_cycles),
            (self.doppler_hz, self.doppler_std_hz),
        ):
            if quantity is None and uncertainty is not None:
                raise ValueError("uncertainty requires its observation")


@dataclass(frozen=True, slots=True, kw_only=True)
class SatelliteState(TimedRecord):
    receiver_id: str
    constellation: Constellation
    sv_id: str
    signal_code: str
    sat_x_m: float
    sat_y_m: float
    sat_z_m: float
    ephemeris_source: str
    ephemeris_hash: str
    transmit_timestamp_ns: int | None = None
    position_frame: Literal["ECEF"] = "ECEF"
    sat_vx_mps: float | None = None
    sat_vy_mps: float | None = None
    sat_vz_mps: float | None = None
    sat_clock_bias_m: float | None = None
    sat_clock_drift_mps: float | None = None
    relativistic_correction_m: float | None = None
    sagnac_correction_m: float | None = None
    iono_delay_m: float | None = None
    tropo_delay_m: float | None = None
    code_bias_m: float | None = None
    elevation_deg: float | None = None
    azimuth_deg: float | None = None
    receiver_position_source: str | None = None
    processing_notes: str | None = None

    def __post_init__(self) -> None:
        super(SatelliteState, self).__post_init__()
        if not re.fullmatch(r"[1-9][A-Z]", self.signal_code):
            raise ValueError("invalid signal_code")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.ephemeris_hash):
            raise ValueError("ephemeris_hash must be sha256:<64 lowercase hex digits>")
        velocity = (self.sat_vx_mps, self.sat_vy_mps, self.sat_vz_mps)
        if any(v is None for v in velocity) and not all(v is None for v in velocity):
            raise ValueError("satellite velocity must be a complete triple or unavailable")
        if self.elevation_deg is not None and not -90 <= self.elevation_deg <= 90:
            raise ValueError("elevation outside [-90, 90]")
        if self.azimuth_deg is not None and not 0 <= self.azimuth_deg < 360:
            raise ValueError("azimuth outside [0, 360)")


@dataclass(frozen=True, slots=True, kw_only=True)
class ImuObservation(TimedRecord):
    sensor_id: str
    frame_id: str
    acc_x_mps2: float
    acc_y_mps2: float
    acc_z_mps2: float
    gyro_x_radps: float
    gyro_y_radps: float
    gyro_z_radps: float
    temperature_c: float | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameTransform:
    """p_to = R(quaternion_wxyz) p_from + translation_m."""

    from_frame: str
    to_frame: str
    translation_m: Vector3 | None = None
    quaternion_wxyz: Quaternion | None = None

    def __post_init__(self) -> None:
        for name, annotation in get_type_hints(type(self)).items():
            if not _matches(getattr(self, name), annotation):
                raise TypeError(f"{name}: invalid transform value")
        if not self.from_frame.strip() or not self.to_frame.strip():
            raise ValueError("transform frames must be named")
        if self.quaternion_wxyz is not None:
            if abs(sum(v * v for v in self.quaternion_wxyz) - 1) > 1e-6:
                raise ValueError("quaternion must have unit norm")


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationMetadata(Record):
    receiver_id: str | None = None
    sensor_id: str | None = None
    gnss_receiver_model: str | None = None
    gnss_antenna_model: str | None = None
    imu_model: str | None = None
    antenna_to_imu_lever_arm_m: Vector3 | None = None
    lever_arm_frame: str | None = None
    frame_transforms: tuple[FrameTransform, ...] | None = None
    time_sync_method: str | None = None
    calibration_source: str | None = None
    calibration_valid: bool | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        super(CalibrationMetadata, self).__post_init__()
        if self.antenna_to_imu_lever_arm_m is not None and self.lever_arm_frame is None:
            raise ValueError("lever arm requires a frame")


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetMetadata(Record):
    city: str | None = None
    environment_label: str | None = None
    gnss_nominal_rate_hz: float | None = None
    imu_nominal_rate_hz: float | None = None
    reference_nominal_rate_hz: float | None = None
    receiver_id: str | None = None
    receiver_model: str | None = None
    imu_model: str | None = None
    available_observables: tuple[str, ...] | None = None
    available_constellations: tuple[Constellation, ...] | None = None
    reference_type: str | None = None
    reference_quality_notes: str | None = None
    known_issues: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        super(DatasetMetadata, self).__post_init__()
        for rate in (self.gnss_nominal_rate_hz, self.imu_nominal_rate_hz, self.reference_nominal_rate_hz):
            if rate is not None and rate <= 0:
                raise ValueError("nominal rates must be positive or unavailable")
