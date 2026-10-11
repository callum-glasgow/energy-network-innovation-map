# Energy network innovation map

[Open the live map](https://callum-glasgow.github.io/energy-network-innovation-map/) · [Download the runnable map](https://github.com/callum-glasgow/energy-network-innovation-map/releases/latest/download/energy-network-map.zip) · [Update guide](docs/updating-map.md)

A portfolio map for innovation project managers and management teams at energy networks. Explore technical similarity, recorded project history, original project evidence, dates and investment totals. This repository contains the **standalone map and its maintenance tools**. It does not contain the separate search/report application.

The first release covers **312 SP Energy Networks projects: 222 Distribution and 90 Transmission**. The tools support adding other owners and approximately 3,200 entries; that expanded catalogue is not included in this release. This is a saved snapshot, not a live ENA feed. At initial publication, a newer ENA download had found 313 SPEN projects; the extra entry was not included in that first snapshot.

## When is the data from?

For the initial release, project descriptions and metadata were checked on **7 October 2026**, and financial fields on **10 October 2026**. The generated table below gives the dates for the latest prepared package. Building or publishing the map later does not refresh these records. Live/Complete reflects the recorded source status; an expired end date alone does not establish completion. Individual projects retain their source/check dates where recorded.

<!-- snapshot-start -->
Snapshot: **312 projects**. Package built **2026-10-11T21:52:47.775447+00:00**.

| Source timestamp | Earliest → latest (UTC) | Records with date |
| --- | --- | --- |
| Project source checked | 2026-10-07T17:50:01.292497+00:00 → 2026-10-07T17:51:01.009073+00:00 | 312/312 |
| Project detail checked | 2026-10-07T17:50:01.292477+00:00 → 2026-10-07T17:51:01.009069+00:00 | 312/312 |
| Financial fields checked | 2026-10-10T15:01:33.147306+00:00 → 2026-10-10T15:01:33.147306+00:00 | 312/312 |
| File imported | Not recorded | 0/312 |

Build time is not a fresh ENA check. Imported records may have no independently checked source date.

Included owners: SP Energy Networks Distribution (222), SP Energy Networks Transmission (90).
<!-- snapshot-end -->

Each downloadable ZIP includes `snapshot-info.json` and a dated `README.txt`. Release notes contain the dates for that particular release. The README describes the latest prepared snapshot on the main branch; use the release's own metadata when opening an older download.

## Download and run it yourself

1. Download **energy-network-map.zip** from [the latest Release](https://github.com/callum-glasgow/energy-network-innovation-map/releases/latest). GitHub's green **Code → Download ZIP** downloads source for developers, not the runnable map.
2. Extract the entire ZIP and open the `energy-network-map` folder.
3. Install [Python 3](https://www.python.org/downloads/) if needed. No other packages or API key are required to view the map.
4. Start it with a terminal in that folder:

```sh
# macOS / Linux
python3 serve.py
```

```powershell
# Windows
py -3 serve.py
```

The included **Start map.command** (macOS) and **Start map.bat** (Windows) launchers are alternatives. If macOS does not allow the downloaded launcher, use the terminal command above. Open **http://127.0.0.1:8766/** if the browser does not open. Use `python3 serve.py --port 9000` (or `py -3 ...`) if the default port is occupied. Stop with Ctrl+C.

Keep the complete extracted folder together. Opening `index.html` directly will not work because browsers restrict local data fetching. The local server listens only on your computer. All map data, filters, comparisons and evidence work offline; external ENA links need internet access.

## Using the map

Choose **Map** to draw the projects, **Overview** to explore similarity groups, **Table** to compare/filter individual entries, or **Management** for portfolio totals. Project size defaults to recorded investment and colour to similarity group. Hover for group, dates, status and connection information; select a project for details below the map. Use **Full screen map** for a larger view and **Fit visible projects** to reset framing.

Lines indicate retained technical matches. Separate groups and unlinked project positions have no distance meaning. An absent link does not prove novelty or exclude related work. Original evidence is available for reviewing comparisons; generated similarity is not proof of duplication, delivery success or benefits. Budget totals can overlap between phases/programmes and are not actual expenditure.

## Update data and add projects

The [full update guide](docs/updating-map.md) covers downloaded CSV/XLSX/JSON files, model caches, failed-run recovery, new entries, all-network expansion and rollback. Source processing and Luna/embedding calls run locally. GitHub Pages only serves the verified static package and needs no model credentials.

For maintainers, set up **Python 3.11**, [Bun](https://bun.sh/) and [GitHub CLI](https://cli.github.com/):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
bun install --frozen-lockfile
cd ..
```

On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe` instead of `.venv/bin/...`. Viewing the downloaded map does not require Bun or these packages.

A fresh clone has no source database or paid model caches. To continue this existing snapshot efficiently, retain the maintainer's local **data/** folder, including its spend ledger. Otherwise the first full import must reconstruct missing model outputs. Never commit this folder or API keys. New/changed text needs a local `OPENAI_API_KEY`; unchanged cached text is reused. The application currently enforces a **$5 lifetime API cap**. It will stop at the cap; the remaining allowance is not guaranteed to cover all networks. Do not delete/reset the spend ledger to bypass it.

Typical SPEN refresh, from the repository folder:

```sh
.venv/bin/python -m scripts.download_ena
.venv/bin/python -m scripts.update_map data/inbox/ena-projects.json
# Review the preview, then apply. --live enables missing paid model work.
.venv/bin/python -m scripts.update_map data/inbox/ena-projects.json --apply --live
# Update the README dates from the exact newly built package.
.venv/bin/python -m scripts.snapshot_info --write-readme README.md
```

For another ENA spreadsheet use its path instead. Missing projects are retained by default, so partial exports cannot silently delete the rest. `--replace` is only for a deliberately complete replacement. To add all ENA owners, use `--scope all` consistently on download, preview and apply; see the guide. Owner filters, counts, groups and management totals are rebuilt from the imported records.

Publish the newly prepared package:

```sh
# Commit any changed source or README, then push to this repository.
git add README.md
git commit -m "Update map snapshot dates"
git push
# Review the package, then create its Release.
.venv/bin/python -m scripts.publish_map --repo callum-glasgow/energy-network-innovation-map
.venv/bin/python -m scripts.publish_map --repo callum-glasgow/energy-network-innovation-map --publish
```

If there are no source/README changes, skip the commit. For code changes, include the intended files in the commit and rebuild with `.venv/bin/python -m scripts.build_map` before publishing. The publisher checks clean source, the pushed commit, package checksums and the build's source fingerprint. Each Release uses a new tag; old downloads remain available.

Publishing a `map-…` Release triggers [the Pages workflow](.github/workflows/deploy-map.yml). It verifies and deploys **the same ZIP** offered for download. Wait for **Deploy prepared project map** to succeed in [Actions](https://github.com/callum-glasgow/energy-network-innovation-map/actions), then check the live map. Pushing source alone does not deploy a dataset. To roll back, run that workflow manually with an earlier release tag.

## Checks and hosting

The [publication verification report](docs/publication-verification.json) records the successful Pages deployment and anonymous ZIP download on 11 October 2026. Checks passed for 44 Python tests, 18 frontend tests, all initial hosted files and the corrected release files. Browser checks covered the graph, project table, original evidence, comparisons, management view and fullscreen. Publication made no paid model calls.

```sh
.venv/bin/python -m unittest discover -s tests
cd frontend
bun test
```

The map loads comparison rows on demand and uses relative asset paths for repository GitHub Pages URLs. At 3,200 entries the dense comparison rows occupy about 369 MB before compression; full-catalogue browser performance still needs measurement with that actual dataset. Builds reject packages at 950 MB, below [Pages' 1 GB site limit](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits). The current 312-entry package is about 10 MB unpacked. No generated dataset is stored in Git history: releases carry the prepared ZIP.

## Source and attribution

Project records and original passages come from the [Energy Networks Association Innovation Portal](https://smarter.energynetworks.org/). Original project links and source field names are retained. **Project data remains subject to [ENA's source licence terms](https://smarter.energynetworks.org/licenses/)**; public availability does not make it unrestricted data. Review those terms before redistribution or reuse. This is an independent project and does not claim ENA or SP Energy Networks endorsement.

“All networks” in the importer means the ENA catalogue it can download. ENA directs gas innovation projects from January 2025 onwards to the Future Energy Networks portal; those newer records need a separate adapter. Do not assume the current ENA export covers all future energy-network projects.
