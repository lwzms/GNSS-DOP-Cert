"""Explicit adapter to the single packaged certificate implementation."""
import importlib.util
from pathlib import Path
_path=Path(__file__).resolve().parents[1]/'toolbox/src/certify.py'
_spec=importlib.util.spec_from_file_location('packaged_finite_input_certificate',_path)
_module=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
certificate=_module.certificate
NAMES=_module.NAMES
