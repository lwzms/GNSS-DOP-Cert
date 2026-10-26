# GNSS-ToolBox-118

Private code and derived-evidence repository limited to the GNSS paper on evidence-separated
qualification and certified finite-input numerical reproducibility.
The executable package is `toolbox/`; start with `toolbox/README.md`.
This repository contains source, tests, configuration templates, dependency and
input/interface documentation, and a bounded paper evidence package. It contains
no manuscripts, full research reports, raw GNSS files, DLLs or numerical-library distributions.

**共同作者从 [复现说明](docs/COAUTHOR_REPRODUCTION.md) 开始。**
使用的数据、文件身份和获取条件见 [数据来源](docs/DATA_SOURCES.md)。
接收者的数据下载、环境建立和固定窗口运行步骤见 [Windows准备指南](docs/SETUP_WINDOWS.md)。
无需原研究目录、NumPy或DLL即可核查保存结果和80项有限输入证书：

```powershell
python -I -B reproduce/verify_paper_evidence.py
```

This read-only command executes zero navigation calls. A PASS verifies the
exported evidence and finite-input arithmetic, not an independent GNSS rerun.

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
- `evidence/urban_spp_fde_v1/`: authorized derived results, qualification rows,
  production matrices, certificates and provenance for the same fixed window.

Other GNSS algorithm prototypes, IMU research, mathematical theory, research
reports and manuscript text are outside this repository. Only the explicitly
listed paper evidence subset is included; the complete historical runs remain local.
The supplementary numerical tools are not new estimators or default acceptance policies.
