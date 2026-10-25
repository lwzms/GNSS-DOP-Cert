"""Pure checks extracted from the frozen UrbanNav final-residual policy.

No files, solver, ephemeris propagation, reference interpolation or quantiles.
Missing evidence remains UNKNOWN. This module is not a realtime solver gate.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math

import numpy as np

VERSION = "URBANNAV_SAVED_QUALIFICATION_V1"
PROTOCOL_ID = "URBANNAV_GPS_C1C_EVAL_V1"
MODEL_SCOPE = "FINAL_RESIDUAL_DOMAIN_V1"
T, F, U = "TRUE", "FALSE", "UNKNOWN"
FLAGS = ("OBS_VALID", "NAV_VALID", "MODEL_VALID", "SOLVER_VALID", "REFERENCE_VALID")
# Numerical rules present in freeze_evaluation.py rather than numeric JSON keys.
SOURCE_RULES = {"toe_max_age_seconds": 7201, "elevation_roundoff_rad": 1e-12,
                "rank_tolerance": "NumPy matrix_rank default: s_max * max(M,N) * eps(float64)"}
REFERENCE_FIELDS = ("nominal_bracketing", "physical_time", "datum_realization", "export_point",
                    "antenna_transfer", "uncertainty_adequacy", "quality_semantics", "dependency_declaration")


def truth(value):
    if value is True or value == T or value == "True":
        return T
    if value is False or value == F or value == "False":
        return F
    if value is None or value == U or value == "":
        return U
    raise ValueError(f"INVALID_TRUTH_VALUE: {value!r}")


def conjunction(values):
    values = list(values)
    if any(v not in (T, F, U) for v in values):
        raise ValueError("INVALID_THREE_VALUE_CONJUNCTION")
    return F if F in values else U if U in values else T


def final_state(obs, nav, model, solver, reference):
    values = [obs, nav, model, solver, reference]
    conjunction(values)  # validate the vocabulary, including UNKNOWN
    if solver != T:
        return "SOLVER_FAILURE"
    if any(v != T for v in (obs, nav, model)):
        return "INVALID_MODEL_OUTPUT"
    return "VALID_ERROR_SAMPLE" if reference == T else "INVALID_REFERENCE"


def decision(value):
    if type(value) is not bool:
        raise ValueError("INTERNAL_DECISION_MUST_BE_BOOL")
    return T if value else F


def finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (ValueError, TypeError, OverflowError):
        return False


def check_fields(row, fields, predicate):
    if any(k not in row or row[k] is None or row[k] == "" for k in fields):
        return U
    try:
        return decision(bool(predicate(row)))
    except (ValueError, TypeError, OverflowError, InvalidOperation):
        return F


def all_rows(rows, fields, predicate):
    return conjunction(check_fields(r, fields, predicate) for r in rows)


def validate_protocol(protocol):
    if protocol.get("protocol_id") != PROTOCOL_ID or protocol.get("model_profile", {}).get("id") != MODEL_SCOPE:
        raise ValueError("UNSUPPORTED_PROTOCOL_OR_MODEL_SCOPE")
    if protocol.get("evidence_logic") != [T, F, U]:
        raise ValueError("UNSUPPORTED_EVIDENCE_LOGIC")
    if "<=7201 s Toe age" not in protocol.get("navigation", ""):
        raise ValueError("SOURCE_NAV_RULE_NOT_DECLARED")
    profile = protocol["model_profile"]
    for k in ("height_m", "minimum_used_satellites", "physical_rank", "maximum_GDOP",
              "minimum_elevation_deg", "FDE_minimum_used_satellites"):
        if k not in profile:
            raise ValueError(f"PROTOCOL_FIELD_MISSING: {k}")
    if not isinstance(profile["height_m"], list) or len(profile["height_m"]) != 2:
        raise ValueError("PROTOCOL_HEIGHT_RANGE_INVALID")
    for v in protocol.get("reference", {}).values():
        if v not in (T, F, U):
            raise ValueError("REFERENCE_CONTRACT_NOT_THREE_VALUED")


def qualify_saved_epoch(epoch, observations, model_rows, protocol, *, time_valid=U):
    """Return checks for one saved candidate; none of the input objects change.

    time_valid comes from the adapter's exact GPST/grid identity check. The
    historical CSVs have no per-row time, so their pinned grid binding is needed.
    """
    validate_protocol(protocol)
    profile = protocol["model_profile"]
    codes = [r for r in observations if truth(r.get("eligible")) == T]
    eligibility_known = conjunction(T if truth(r.get("eligible")) != U else U for r in observations)
    obs_checks = {
        "recorded_time": truth(time_valid),
        "eligibility_evidence": eligibility_known,
        "nonempty": decision(len(codes) > 0) if eligibility_known == T or codes else U,
        "distinct_satellites": decision(len({r.get("satellite") for r in codes}) == len(codes)),
        "gps_C1C_identity": all_rows(codes, ["satellite"], lambda r:
            isinstance(r["satellite"], str) and len(r["satellite"]) == 3
            and r["satellite"][0] == "G" and r["satellite"][1:].isdigit()
            and 1 <= int(r["satellite"][1:]) <= 32),
        "finite_positive_code": all_rows(codes, ["C1C_raw"], lambda r:
            Decimal(str(r["C1C_raw"])).is_finite() and Decimal(str(r["C1C_raw"])) > 0),
    }
    obs_valid = conjunction(obs_checks.values())
    used = [r for r in model_rows if truth(r.get("used")) == T]
    usage_unknown = any(truth(r.get("used")) == U for r in model_rows)
    nav_checks, checks, legacy_reasons = {}, {}, []
    rank = None
    singular_values = None
    rank_tolerance = None
    if used and not usage_unknown:
        nav_checks = {
            "record_present": all_rows(used, ["orbit_record"], lambda r: int(r["orbit_record"]) >= 0),
            "health": all_rows(used, ["health"], lambda r: int(r["health"]) == 0),
            "IOD": all_rows(used, ["iodc", "iode"], lambda r: int(r["iodc"]) % 256 == int(r["iode"])),
            "week": all_rows(used, ["week", "tx_week"], lambda r:
                    int(r["week"]) == int(r["tx_week"]) == int(epoch["week"])) if epoch.get("week") not in (None, "") else U,
            "toe_age": all_rows(used, ["tx_tow", "toe"], lambda r:
                abs(float(r["tx_tow"]) - float(r["toe"])) <= SOURCE_RULES["toe_max_age_seconds"]),
            "fit_interval": all_rows(used, ["fit_hours", "tx_tow", "toe"], lambda r:
                float(r["fit_hours"]) > 0 and abs(float(r["tx_tow"]) - float(r["toe"])) <= float(r["fit_hours"]) * 1800),
            "orbit_clock_finite": all_rows(used, ["sat_x_m", "sat_y_m", "sat_z_m", "sat_clock_total_s", "af0", "af1", "af2", "relativity_s"],
                lambda r: all(finite(r[k]) for k in ["sat_x_m", "sat_y_m", "sat_z_m", "sat_clock_total_s", "af0", "af1", "af2", "relativity_s"])),
        }
        nav_valid = conjunction(nav_checks.values())
    else:
        nav_valid = U
        legacy_reasons.append("USED_NAV_ROWS_UNAVAILABLE")
    if epoch.get("state_ecef_m") is not None and used and not usage_unknown:
        state = epoch["state_ecef_m"]
        state_ok = isinstance(state, (list, tuple)) and len(state) == 3 and all(finite(v) for v in state)
        if all(all(k in r and r[k] not in (None, "") for k in ["los_x", "los_y", "los_z"]) for r in used):
            if all(all(finite(r[k]) for k in ["los_x", "los_y", "los_z"]) for r in used):
                h = np.array([[-float(r["los_x"]), -float(r["los_y"]), -float(r["los_z"]), 1.] for r in used], dtype=np.float64)
                singular_values = np.linalg.svd(h, compute_uv=False).tolist()
                rank_tolerance = singular_values[0] * max(h.shape) * np.finfo(h.dtype).eps
                rank = int(np.linalg.matrix_rank(h))
                rank_check = decision(rank == profile["physical_rank"])
            else:
                rank_check = F
        else:
            rank_check = U
        lo, hi = profile["height_m"]
        fde_required = conjunction([truth(epoch.get("accepted")), truth(epoch.get("FDE_attempted"))])
        fde_count = T if fde_required == F else decision(len(used) >= profile["FDE_minimum_used_satellites"]) if fde_required == T else U
        checks = {
            "state_finite": conjunction([decision(state_ok), check_fields(epoch, ["clock_m"], lambda r: finite(r["clock_m"]))]),
            "height_domain": check_fields(epoch, ["model_height_m"], lambda r: lo <= float(r["model_height_m"]) <= hi),
            "minimum_satellites": decision(len(used) >= profile["minimum_used_satellites"]),
            "used_set_consistent": check_fields(epoch, ["used_satellites"], lambda r:
                {v.get("sv") for v in used} == set(r["used_satellites"])),
            "physical_rank": rank_check,
            "GDOP": check_fields(epoch, ["gdop"], lambda r: finite(r["gdop"]) and 0 < float(r["gdop"]) <= profile["maximum_GDOP"]),
            "elevation": all_rows(used, ["el_rad"], lambda r:
                float(r["el_rad"]) >= math.radians(profile["minimum_elevation_deg"]) - SOURCE_RULES["elevation_roundoff_rad"]),
            "corrections_finite": all_rows(used, ["iono_m", "trop_m", "sagnac_m", "applied_tgd_m", "raw_code_m", "corrected_code_m", "predicted_raw_code_m", "residual_m"],
                lambda r: all(finite(r[k]) for k in ["iono_m", "trop_m", "sagnac_m", "applied_tgd_m", "raw_code_m", "corrected_code_m", "predicted_raw_code_m", "residual_m"])),
            "variance_positive": all_rows(used, ["variance_m2"], lambda r: finite(r["variance_m2"]) and float(r["variance_m2"]) > 0),
            "signal_and_row_eligible": all_rows(used, ["sv", "model_eligible"], lambda r:
                r["sv"] in {v["satellite"] for v in codes} and int(r["model_eligible"]) == 1),
            "FDE_minimum_satellites": fde_count,
        }
        model_valid = conjunction([obs_valid, nav_valid, *checks.values()])
    else:
        model_valid = U
        legacy_reasons.append("FINAL_MODEL_METADATA_UNAVAILABLE")
    state = epoch.get("state_ecef_m")
    state_truth = U if state is None else decision(isinstance(state, (list, tuple)) and len(state) == 3 and all(finite(v) for v in state))
    solver_checks = {"original_accepted": truth(epoch.get("accepted")), "returned_position_finite": state_truth,
                     "returned_clock_finite": check_fields(epoch, ["clock_m"], lambda r: finite(r["clock_m"]))}
    solver_valid = conjunction(solver_checks.values())
    ref_checks = {k: protocol.get("reference", {}).get(k, U) for k in REFERENCE_FIELDS}
    ref_valid = conjunction(ref_checks.values())
    legacy_reasons += ["MODEL_" + k.upper() for k, v in checks.items() if v != T]
    legacy_reasons += ["NAV_" + k.upper() for k, v in nav_checks.items() if v != T]
    legacy_reasons += ["REFERENCE_" + k.upper() + "_UNKNOWN" for k, v in ref_checks.items() if v == U]
    check_groups = dict(zip(FLAGS, [obs_checks, nav_checks, checks, solver_checks, ref_checks]))
    reason_codes = {flag: [f"{flag}.{k}.{v}" for k, v in group.items() if v != T] for flag, group in check_groups.items()}
    if checks:
        reason_codes["MODEL_VALID"] += [f"DEPENDENCY.{k}.{v}" for k, v in [("OBS_VALID", obs_valid), ("NAV_VALID", nav_valid)] if v != T]
    if not used or usage_unknown:
        reason_codes["NAV_VALID"].append("USED_NAV_ROWS_UNAVAILABLE")
    if not checks:
        reason_codes["MODEL_VALID"].append("FINAL_MODEL_METADATA_UNAVAILABLE")
    result = dict(zip(FLAGS, [obs_valid, nav_valid, model_valid, solver_valid, ref_valid]))
    result.update({"FINAL_STATE": final_state(obs_valid, nav_valid, model_valid, solver_valid, ref_valid),
                   "obs_checks": obs_checks, "nav_checks": nav_checks, "model_checks": checks,
                   "solver_checks": solver_checks, "reference_checks": ref_checks,
                   "reason_codes": reason_codes, "reasons": legacy_reasons,
                   "physical_satellite_count": len(used), "physical_rank_rechecked": rank,
                   "physical_dof": len(used) - profile["physical_rank"] if used else None,
                   "fault_monitor_redundancy": decision(len(used) > 4) if used else U,
                   "physical_singular_values": singular_values, "rank_tolerance": rank_tolerance,
                   "MODEL_SCOPE": MODEL_SCOPE, "FULL_PHYSICAL_MODEL_CONTRACT": U, "ITERATION_PATH_DOMAIN": U})
    return result
