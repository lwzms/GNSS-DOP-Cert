# GNSS-ToolBox-118

Private code-only repository limited to the GNSS paper on evidence-separated
qualification and certified finite-input numerical reproducibility.
The executable package is `toolbox/`; start with `toolbox/README.md`.
This repository contains source, tests, configuration templates, dependency and
input/interface documentation. It contains no manuscripts, research reports,
raw GNSS data, run results, DLLs or numerical-library distributions.

The current scientific contract is restricted to the previously specified
20-epoch UrbanNav window. Other inputs and platforms are not certified.
Ordinary execution and optional exact historical comparison are separate modes.
Reference UNKNOWN is not a positioning accuracy certificate.

## Entry

```powershell
python -I -B toolbox/toolbox.py --version
python -I -B toolbox/toolbox.py --help
python -I -B toolbox/toolbox.py preflight --config C:/your-work/config.json
python -I -B toolbox/toolbox.py run --config C:/your-work/config.json
python -I -B toolbox/toolbox.py verify --run-dir C:/your-work/runs/your_run
```

Create configurations and run outputs outside `toolbox/` and the repository.
The operator must supply legally obtained OBS, NAV, DLL and a compatible Python
environment. No automatic download or replacement is performed.
See `docs/INPUT_AND_INTERFACE.md` and the packaged dependency contracts.

This repository has a new Git history. Historical checkouts and local bundles
remain archival; never push their old branches into this repository.
No public redistribution licence is granted by this private storage operation.

## Paper reproduction scope

- `toolbox/`: standard SPP/FDE execution, model/solver/reference qualification,
  production DOP recording, exact comparison and finite-input certificates.
- `reproduce/`: fixed-angle/H/G/Q numerical replay, conditional offline comparison,
  and layered failure-receipt inspection using explicitly supplied saved inputs.
- `docs/`: input sources, injected paths, dependency and result-interface contracts.

Other GNSS algorithm prototypes, IMU research, mathematical theory, research
reports, manuscript text and historical result arrays are outside this repository.
The supplementary numerical tools are not new estimators or default acceptance policies.
