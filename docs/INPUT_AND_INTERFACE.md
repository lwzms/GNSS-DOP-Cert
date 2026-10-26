# Data sources and injected interfaces

The external input contract binds three user-provided files by SHA256:
UrbanNav-HK-Medium-Urban-1 rear F9P splitter GPS C1C observations;
BKG/IGS/DLR BRDM00DLR_S_20211370000_01D_MN.rnx broadcast ephemerides;
the project-specific Windows AMD64 RTKLIB wrapper DLL. Their exact hashes,
sizes and source descriptions are in `toolbox/external_inputs_contract.json`.
They are not distributed here. Public availability does not establish redistribution rights.

Copy `toolbox/config.template.json` outside the source package. Supply paths and
identities for OBS, NAV, DLL and Python. Relative paths resolve against the
configuration directory. UNC/device paths and unsafe output paths are rejected.
The current window, signal, methods, variance and FDE policies remain frozen;
the interface does not silently select another file or change scientific parameters.
No ground truth or saved navigation result enters initialization.

Use `INTERNAL_STANDARD_RUN_V1` with historical_comparison=null for ordinary execution.
`EXACT_HISTORICAL_REGRESSION_V1` requires a separately supplied, hash-bound historical
contract and results. Absence of those files is not a dependency of ordinary execution.
The bounded paper evidence subset is now included under `evidence/urban_spp_fde_v1`.
It does not include the complete historical run directory required by the legacy
12965-field comparator. Saved comparison receipts are labeled as historical;
the portable verifier recalculates only its explicitly documented subset.

Production DOP recording captures intermediate matrices; it does not alter
navigation decisions. Finite-input numerical certificates do not supersede
the exact historical comparator or certify physical position accuracy.

The legacy E0 provenance filenames now contain a new, explicitly identified
code-only adapter. Their hashes and the package inventories have been rebuilt.
No original E0 certificate is claimed for the adapter. Python and physical
configuration bytes remain unchanged; this packaging task executes no navigation.
