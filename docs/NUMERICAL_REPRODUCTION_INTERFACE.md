# Saved-input numerical reproduction interface

These tools use externally supplied saved inputs and never propagate satellites
or run SPP/FDE. The bounded `evidence/urban_spp_fde_v1/` export now supplies
saved production angles, matrices, derived positions and certificates. Start with
`reproduce/verify_paper_evidence.py`; it accepts this export directly and uses
the Python standard library only. Its input format differs from the legacy
numeric_worker INPUT.json contract described below; do not pass the export
directory to that worker as if it were an E15 input file.

`reproduce/numeric_worker.py` accepts --mode angles|H|G|Q, --inputs INPUT.json,
optional --source MATRIX_DIRECTORY, and --out NEW_DIRECTORY. INPUT.json is the
saved angle contract with an E12 array of request rows. Each row has key,
source_epoch_index, and nodes containing used, az_raw and el_raw. Original order
and binary64 conversions must be retained. H/G/Q modes consume the corresponding
zero-padded NPY files emitted by a prior offline invocation. Output directories
must be new. The worker records loaded numeric binaries and refuses a loaded
GNSS DLL. It targets the documented Windows numerical environments.

The exact certificate implementation is canonical at `toolbox/src/certify.py`.
`reproduce/certify.py` is only an import adapter; no second numerical formula is
maintained. `candidate_compare.compare(old,new,left,right)` expects explicit
science identities, exact A-class fields, DOP arrays and bound matrix records.
It is an offline finite-input candidate and cannot replace exact historical comparison.

`reproduce/failure_recorder.py --run-dir SAVED_RUN --comparison COMPARISON.json`
reads saved execution and comparison receipts. Missing evidence remains UNKNOWN;
the current inspection has zero navigation calls even when historical counts
are nonzero. A failed strict comparison retains a nonzero exit code.

Keep generated files outside the repository. Supply authorized immutable inputs
and record their hashes before invoking these scripts. This repository separation
does not itself rerun any numerical experiment or navigation calculation.
