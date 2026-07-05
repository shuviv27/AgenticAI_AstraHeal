# GUI Startup Syntax Hotfix

## Issue

On Windows/VM startup, the GUI failed during FastAPI import with:

```text
SyntaxError: f-string expression part cannot include a backslash
```

The failing line was in:

```text
qa_pipeline/agents/existing_framework_control/controller.py
```

## Root cause

Python does not allow a backslash escape directly inside an f-string expression such as:

```python
f"{str(rel).replace('\\', '/')}: {exc}"
```

## Fix

The path normalization is now calculated before the f-string:

```python
rel_text = str(rel).replace("\\", "/")
skipped.append(f"{rel_text}: {exc}")
```

## Validation

Validated after patch:

```text
python -m compileall -q qa_pipeline
python -c "import qa_pipeline.gui.app as app; print('APP_IMPORT_OK')"
```

Both passed.
