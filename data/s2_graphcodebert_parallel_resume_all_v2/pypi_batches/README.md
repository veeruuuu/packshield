# S2 PyPI feature extraction batches

Four independent PyPI-only inputs. Target size is 3,000 packages: three batches of 3,000 and a final remainder. Each batch has a standalone PowerShell launcher and isolated timestamped outputs. Launchers run three parser shards (one worker each), archive batch size four, and read package contents from the PyPI Git archive only; they never install or execute package code. The required npm-root argument is passed for CLI compatibility, but all input rows have ecosystem `pypi`.

Before launch, set `S2_PYPI_ROOT` (and optionally `S2_NPM_ROOT` to the project-adjacent npm checkout), then run the desired `run_pypi_batch_XX.ps1`. The assignments and counts are in `package_assignments.csv` and `batch_manifest.json`. Do not run the same batch twice at the same time.
