## 🧪 Development tests

For local development on Windows, run tests from the repo root with:

```powershell
pytest tests\test_play_ir_blob.py -q
```

The checked-in `pytest.cmd` wrapper automatically picks a project Python in this order:

1. `.venv-py313`
2. `.venv-py313-smoke`
3. `.venv`

So the shell doesn't need an activated virtual environment as long as one of those folders exists and has `pytest` installed.

If you are setting up a new machine, the most compatible default is:

```powershell
py -3.13 -m venv .venv-py313
.venv-py313\Scripts\python -m pip install -U pip pytest
```

After that, plain `pytest ...` from the repository root should work.

---
