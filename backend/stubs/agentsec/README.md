# agentsec (stub)

Placeholder package so `from agentsec.session import ...` resolves while the real `agentsec` orchestrator is not installed.

Replace with the real package:

```bash
pip uninstall -y agentsec
pip install -e /path/to/agentsec
```

The stub honors `AGENTSEC_STUB_BEHAVIOR` for deterministic tests (see `session.py`).
