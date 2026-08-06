# Releasing Hirara to PyPI

Hirara publishes its pip-installable packages with **PyPI Trusted Publishing**
(OIDC). GitHub Actions proves the release came from this repository, and PyPI
mints a short-lived, project-scoped token for that one upload. **There is no API
token to create, store, or rotate**, and the workflow
([`.github/workflows/pypi-publish.yml`](.github/workflows/pypi-publish.yml))
never sees a long-lived secret.

## Packages published

| PyPI project   | Source path     | Import        | Version source              |
| -------------- | --------------- | ------------- | --------------------------- |
| `hirara-core`  | `hirara-core/`  | `hirara_core` | `hirara-core/pyproject.toml`|
| `hirara-web`   | `.` (repo root) | `hiraraweb`   | `pyproject.toml`            |
| `hirarapdf`    | `hirarapdf/`    | `hirarapdf`   | `hirarapdf/pyproject.toml`  |
| `hirarareader` | `hirarareader/` | `hirarareader`| `hirarareader/pyproject.toml`|
| `hirara` (SDK) | `hirara/`       | `hirara`      | `hirara/pyproject.toml`     |

Each package is versioned **independently**. A git tag only *triggers* a
release; the version that lands on PyPI is whatever each `pyproject.toml` says.
PyPI versions are **immutable** — you cannot overwrite one — so the workflow uses
`skip-existing: true`: already-published versions are skipped, and only packages
whose version changed are actually uploaded.

## One-time setup: configure the publishers

Do this once per package. It reserves the four unclaimed names at the same time
(a "pending publisher" both authorizes the upload *and* claims the name on first
publish, so no one can squat it in the meantime).

Every publisher uses the same Owner `lucasdmarshall`, Repository `Hirara`, and
Workflow `pypi-publish.yml` — but a **different Environment name per package**.
That is required: PyPI refuses two *pending* publishers that share an identical
owner/repo/workflow/environment tuple ("a pending trusted publisher matching
this configuration has already been registered for a different project name"),
so a blank environment can only ever cover one package. The environment names
below match the ones the workflow sends.

| PyPI project   | Environment name |
| -------------- | ---------------- |
| `hirara-core`  | `pypi-core`      |
| `hirara-web`   | `pypi-web`       |
| `hirarapdf`    | `pypi-pdf`       |
| `hirarareader` | `pypi-reader`    |
| `hirara`       | `pypi-sdk`       |

### On PyPI (https://pypi.org)

- **`hirara`** already exists (you own it). Open it → **Manage → Publishing →
  Add a new publisher**: Owner `lucasdmarshall`, Repository `Hirara`, Workflow
  `pypi-publish.yml`, Environment `pypi-sdk`.
- **`hirara-core`, `hirara-web`, `hirarapdf`, `hirarareader`** do not exist yet.
  Go to **Your account → Publishing** (https://pypi.org/manage/account/publishing/)
  — that page has the extra **PyPI Project Name** field, which is what makes it a
  *pending* publisher. Add one per name with its Environment from the table.

> GitHub creates the five environments (`pypi-core`, … `pypi-sdk`) automatically
> the first time the workflow runs. No manual GitHub setup is needed; if a run
> ever reports a missing environment, add it under **Settings → Environments**.

### On TestPyPI (https://test.pypi.org) — for dry runs

Repeat the **pending publisher** step for all five names on TestPyPI, using the
same Environment names. This lets you rehearse a release without touching PyPI.

## Dry run (TestPyPI)

1. GitHub → **Actions → Publish to PyPI → Run workflow**.
2. Set **target = `testpypi`** and run.
3. Confirm all five jobs are green and the versions appear on
   https://test.pypi.org/project/hirara/ etc.

> TestPyPI cannot resolve third-party deps (httpx, pypdf, …), so
> `pip install` *from* TestPyPI may fail — that is expected. The dry run
> validates the **build and upload**, not a full install.

## Real release

1. Bump the `version` in the `pyproject.toml` of every package you are releasing
   (and `__version__` where the package tracks it). Leave unchanged packages
   alone — their upload will simply be skipped.
2. Commit the bumps.
3. Tag and push:
   ```bash
   git tag -a v0.2.0 -m "Local mode: run web/pdf/office tools in-process"
   git push origin v0.2.0
   ```
4. The workflow builds and publishes to **real PyPI**. Watch the Actions run;
   each package job reports published-or-skipped.

## Verify

```bash
pip install "hirara[local]"
python -c "import hirara; hirara.configure(local=True); print([t['name'] for t in hirara.tools()])"
```

You should see the in-process tools (`pdf_read`, `web_fetch`, `office_read`, …)
with no hub running.
