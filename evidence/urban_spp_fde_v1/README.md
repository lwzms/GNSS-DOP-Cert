# Fixed-window derived paper evidence, version 1

This authorized private export contains existing E16 production results for two
numerical environments, each processing the SAME 20 GPS epochs with SPP and
SPP_FDE. No new navigation was executed to create this export. It contains no
manuscript, raw RINEX, GNSS DLL, runtime binary, ground truth or author information.

Start with `../../docs/COAUTHOR_REPRODUCTION.md` and run
`python -I -B reproduce/verify_paper_evidence.py` from the repository root.
The verifier uses the standard library and the single packaged exact certificate
implementation. It rechecks all exported file hashes, 480 NPY arrays, 80 finite-H
certificates, qualification counts and 160 paired DOP entries. It does not rerun
SPP/FDE, revalidate raw observations, re-execute the full 12965-field comparator,
or certify positioning accuracy.

## Members and interpretation

- `data_sources.json`: exact external input identities and fixed scientific window.
- `environments.json`: sanitized historical binary/build evidence; no installer.
- `arms/A`, `arms/B`: MKL and OpenBLAS environments. Within each arm, method A is
  SPP and method B is SPP_FDE; do not conflate these two uses of A/B.
- `fresh_results.json`: 40 derived results per environment, including original
  accepted/converged flags and failed epochs.
- `qualifications.csv`: unchanged historical qualification rows. References to
  full satellite-term tables are provenance pointers, not included dependencies.
- `matrices/*/record.json`: original numeric fields with machine paths removed;
  the explicitly retained original record hash binds the unmodified historical
  seal and certificates. Export hashes differ because metadata was redacted.
- Six NPYs per request: unchanged binary64 production angles, H, G, Q, Q diagonal
  and ordered diagonal sums. These are E16 runtime matrices, not reconstructed
  historical E12/E13 matrices.
- `production_certificates.json`: original 40 certificates per arm. The status
  label contains E15 because that is the certificate method identifier; these
  certificates bind E16 production records.
- `original_recording_seal.json`: unchanged original receipt, including references
  to runtime files omitted for privacy. It is NOT the manifest of this subset.
- `public_receipt.json`: layered original success/failure evidence. Environment B
  retains exit code 2 and strict regression failure despite valid finite-input certificates.
- `comparisons/`: sanitized saved comparisons, not a newly executed full comparison.
- `fixed_input_stage_summary.json`: original E15 offline decomposition summary,
  including fixed-G inverse differences (587/640); E16 production Q differs in
  594/640 cells. Full E15 exchange matrices are not exported or rerun here.
- `dop_pairs.csv`: 160 paper-source pair rows, regenerated checks against E16
  matrices and exact certificate bounds; signed B-minus-A differences in unitless
  DOP, with nonnegative bounds applied to their absolute values.
- `source_provenance.json`: original and export SHA256 with transformation labels.
- `manifest.json`: complete exported inventory plus verification-code hashes.

There are 131 DOP differences and no automatic tolerance relaxation. All reference
qualifications remain UNKNOWN. This package does not supersede the failed E13
exact replay or make the candidate a new navigation estimator. Hashes provide
integrity relative to a trusted commit, not a signature or independent provenance.
Public redistribution of external data/binaries remains unapproved.
