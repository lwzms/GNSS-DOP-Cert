# Evidence-export validation receipt

This technical receipt concerns the derived paper evidence export only. It does
not replace E11–E18, authorize an independent navigation deployment, or alter any
historical scientific decision.

Locally executed on Windows with CPython 3.14.0, using `-I -B`:

| Check | Actual result |
|---|---|
| Standard-library evidence verifier | PASS |
| Recomputed finite-input certificates | 80 |
| Checked binary NPY files | 480 |
| Paired DOP values / unequal values | 160 / 131 |
| Maximum absolute DOP difference | 9.237055564881302e-12 |
| Synthetic corruption / integrity controls | 10 tests passed |
| Relocated repository copy, execution outside its directory | PASS |
| Relocated tree hashes before/after verification | Unchanged |
| Historical directly used source hashes | 578 unchanged |
| New navigation calls / new raw RINEX scientific parsing | 0 / 0 |
| Actual independent coauthor deployment | NOT_PERFORMED |

The relocation used this same Windows host and standard-library Python; it was
not a clean Windows machine or a second human reproduction. The portable verifier
was tested with CPython 3.14.0, whereas the unchanged production navigation package
still has its own CPython 3.13.5/NumPy 2.1.3 contract. Do not change that contract
because the evidence-only verifier runs on another interpreter.

A separate attempt to launch the previously saved E13 Python 3.13.3 environment
failed before Python execution with process-launch exit code 101. No certificate
or navigation calculation occurred in that attempt. This export does not claim
the old virtual environment remains relocatable or operational on a coauthor's
machine. No replacement packages were installed.

The first new verifier run rejected the signed CSV difference column because the
verifier initially compared it with an absolute difference. Inspection established
that the immutable CSV defines B minus A. The verifier was corrected to compare
the signed exact fraction and to apply bounds to its absolute value. The CSV,
historical outputs and scientific rules were unchanged. A subsequent full check
passed. Initial receipts and the previous verifier source are retained in the
local export audit, outside the repository.

The ten tests cover extra/missing/changed files, verifier identity, altered NPY
bytes, altered JSON matrix values, missing requests, forged certificates,
manifest path escape and read-only inventory checks. All mutations occur in
temporary test copies. Full successful verification also checks the accepted
MODEL_FALSE case, UNKNOWN reference status and retained strict failure exit code.

Existing `toolbox/vendor/recorded_core/README.md` contains archival developer-path
examples, and `toolbox/tests/test_delivery.py` has an optional historical fixture
path. They predate this export and remain byte-identical to the frozen package.
They are not instructions or dependencies for the portable evidence command.
Use `docs/COAUTHOR_REPRODUCTION.md` and `toolbox/toolbox.py` for current entry
instructions; do not invoke legacy vendor scripts as an alternative setup route.

Security review found no newly exported credentials, personal machine paths,
manuscript files, raw OBS/NAV, DLLs or numerical runtime distributions. Source
identifiers are relative provenance labels. Arbitrary substrings within exact
integer certificates are not usernames and have not been redacted.
