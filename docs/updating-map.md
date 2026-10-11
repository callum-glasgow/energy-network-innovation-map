# Updating the project map

The update tools run on your computer. Download an ENA export, preview the changes, then apply them. The script updates project records, generates missing Luna profiles and embeddings, rebuilds similarity scores, groups, layouts, filters, management totals and original evidence, and produces a verified website plus downloadable ZIP. GitHub Pages deploys that same ZIP without an API key or model calls.

The public map is published through verified GitHub Releases and GitHub Pages. The initial saved catalogue has **312 SPEN Distribution/Transmission projects**. The import defaults to those owners; `--scope all` is available when you deliberately expand to the other networks.

## One-time local setup

Use Python 3.11 and Bun, from the repository folder:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
bun install --frozen-lockfile
cd ..
```

If this workspace is already working, just install the updated requirements. For updates needing new model outputs, provide `OPENAI_API_KEY` in the terminal environment using your usual secret manager. Do not put it in source files, GitHub, a spreadsheet or the frontend. The Python model adapter reads it directly; these commands do not load a `.env` file automatically.

Keep `data/` on your local machine and back it up. It contains the source database, reusable model results, update checkpoints and the shared spend ledger. A fresh clone does not contain these caches: reconstructing the index can incur model charges. Keep `data/spend.sqlite3` when moving to a new computer; do not reset it to get more budget.

## 1. Get the latest ENA projects

The easiest repeatable route is the download helper:

```sh
.venv/bin/python -m scripts.download_ena
```

It saves `data/inbox/ena-projects.json`. It reads the public ENA catalogue and rich export, includes original descriptive fields and metadata, preserves ENA GUIDs, and handles shared project references with individual GUID requests. It replaces the download only after the full selected catalogue has been reconciled. It makes no Luna or embedding calls. The ENA export endpoint is not a versioned API; schema or completeness changes stop the download instead of replacing it with a partial file.

Alternatively use [ENA Search](https://smarter.energynetworks.org/search-results/): select the two SP Energy Networks owner networks, choose **Export all results to spreadsheet**, **Select All** fields, and **Download spreadsheet**. Save the file under `data/inbox/`. The importer accepts `.csv`, `.xlsx` or `.json`; save older `.xls` files as `.xlsx` or CSV first. Include **Project Title, Owner Network and Project Reference Number**, all narratives, status, dates, investment, technology/research categories and predecessor fields. A GUID/Project ID column is accepted when available.

Without GUIDs the importer resolves owner/reference against the current public ENA catalogue. Shared or missing references block the import: use the download helper for these instead of inventing IDs or matching on title. For offline identity resolution, add `--catalogue path/to/catalogue.json` using a saved catalogue containing `Results` with `Key`, `OwnerNetwork` and `ProjectReferenceNumber`. A `--mapping fields.json` file can map canonical ENA field keys to renamed spreadsheet headers, for example `{"projectTitle":"Name","ownerNetwork":"Network"}`. Normal ENA headers need no mapping.

## 2. Preview the update

```sh
.venv/bin/python -m scripts.update_map data/inbox/ena-projects.json
```

For a manually downloaded spreadsheet, replace the filename in this and the next command. Preview reports new entries, changed narratives, changed metadata, unchanged entries and retained entries, plus the missing Luna profiles, profile embeddings and original passage embeddings. It shows the remaining application API budget. It makes no paid calls and leaves the current database, website and ZIP in place. A spreadsheet without GUIDs may require the read-only ENA catalogue lookup described above.

Any invalid date, duplicate identity or ambiguous reference blocks the entire import. UK day/month/year and ISO dates are accepted. A source status remains authoritative: a past end date alone does not turn Live into Complete. Missing spreadsheet columns preserve existing values; explicitly blank cells clear the supplied field. Re-importing an unchanged download does not regenerate its model outputs.

By default absent entries remain active. This protects against downloading a filtered or incomplete spreadsheet. Only for an intentionally complete export, add `--replace` to **both** preview and apply: it deactivates absent entries within the selected owner scope. A SPEN replacement preserves other networks already in the local database. No export with zero accepted rows can clear the catalogue.

## 3. Apply, index and rebuild

```sh
.venv/bin/python -m scripts.update_map data/inbox/ena-projects.json --apply --live
```

`--apply` authorises the local update. `--live` explicitly enables any required paid calls. If the preview shows no missing model outputs, you can omit `--live`.

The script uses the existing validated **gpt-6-luna** profile recipe and **text-embedding-3-large, 1024 dimensions**. Profiles are cached against the selected source, useful technical metadata, prompt and schema; embeddings are cached against their exact input, model and dimensions. A status/date/investment change reuses the technical profile. A changed narrative or useful technical metadata invalidates the affected profile; only new or changed passage texts need passage embeddings. API calls remain under the existing shared **$5 lifetime application cap**. This is not a promise that the remaining budget will cover 3,200 entries. Expanding that budget requires a separate, deliberate change; the updater does not bypass it.

Indexing uses a prepared SQLite copy in `data/map-updates/`. It saves each completed profile and embedding, then builds and validates the complete package before updating the live source database and map. Existing reports and query caches are preserved. Projects without usable selected source text remain visible as missing evidence; no narrative is fabricated. File imports are labelled as imports rather than claiming a fresh project-page check.

Successful output:

- `frontend/map-dist/` — complete static website, used by the local map server.
- `outputs/energy-network-map.zip` — the identical map for GitHub Releases and offline use.
- `data/map-updates/<job>/state.json` and `build.json` — update counts, checkpoint, backup path and package hash.
- `data/backups/` — pre-update source database snapshots. These do not replace your spend-ledger backups.

Run the updated map:

```sh
.venv/bin/python frontend/map-dist/serve.py
```

Open [the map](http://127.0.0.1:8766/). A running map server reads the replaced package on the next reload. This repository and its static package contain the map only.

If only frontend/source code changes, rebuild the package without importing or calling models:

```sh
.venv/bin/python -m scripts.build_map
```

## Interrupted or failed updates

Repeat the **same apply command and input file** to resume. Completed model outputs in that job are reused. A failed model call or build leaves the last published local map in place. API/transport failures do not retry automatically, and ambiguous failures retain their budget reservation. Check the reported error before retrying. If the budget is exhausted, the job stops with its progress saved.

The source/index revision is checked before promotion so an older preparation cannot overwrite a newer import. Finish refresh/index jobs before updating; do not run two catalogue writers together. The updater creates `map-update.lock` in its work folder. A hard process termination can leave it behind: remove it only after checking that the process has stopped. If the source changed since a saved job began, the updater stops; preserve that job and use `--work-dir data/map-updates-new` to prepare against the new baseline. Paid results from the abandoned job remain in its prepared database, rather than silently being written into the newer live source.

Database promotion is transactional. The directory and ZIP are then replaced individually; a hard interruption between those replacements can leave the local website and ZIP at different revisions until the same command is resumed. The checkpoint also recovers a termination immediately after the database transaction. Nothing is uploaded until the separate publish step below.

For a local rollback, stop source writers, preserve the current database, and restore the reported pre-update backup using SQLite's backup API into the source database; rebuild with `scripts.build_map`. Keep the spend ledger and reports backed up separately. A Pages rollback needs only the earlier Release, as described below.

## 4. Set up GitHub once, when ready

For a fork or a new installation, create a repository and push the source including `.github/workflows/deploy-map.yml`, `scripts/`, `core/`, `adapters/`, requirements and frontend source. Review what you commit: `.gitignore` excludes `data/`, `outputs/`, built websites, dependencies and `.env`. Do not add a SQLite database, model cache, ledger, key or large generated map files with `git add -f`.

In the GitHub repository, open **Settings → Pages → Build and deployment → Source → GitHub Actions**. If a `github-pages` environment has deployment branch/tag restrictions, allow your `map-*` release tags. Install [GitHub CLI](https://cli.github.com/) locally and sign in with `gh auth login`. On macOS, Git needs working Command Line Tools. If a separate Xcode licence blocks the Git shim while Command Line Tools is installed, run Git with `DEVELOPER_DIR=/Library/Developer/CommandLineTools`; no global Xcode setting change is needed.

A normal source update is reviewed, committed and pushed first, for example:

```sh
git status
git add README.md docs/updating-map.md scripts/ adapters/ core/ tests/ requirements.txt .github/workflows/deploy-map.yml
git commit -m "Update map source and snapshot dates"
git push
```

Use the repository and branch you intend to publish. The helper does not create repositories, commit or push on your behalf. After an update, run `.venv/bin/python -m scripts.snapshot_info --write-readme README.md` and commit the resulting snapshot-date block before publishing. No model caches or databases need to be committed.

## 5. Publish the updated package

Use `callum-glasgow/energy-network-innovation-map` for this repository, or replace it with your fork. First preview and verify locally:

```sh
.venv/bin/python -m scripts.publish_map --repo callum-glasgow/energy-network-innovation-map
```

When you choose to upload it:

```sh
.venv/bin/python -m scripts.publish_map --repo callum-glasgow/energy-network-innovation-map --publish
```

The publisher requires clean committed source and verifies that the exact current commit exists in the chosen repository. A source fingerprint also checks that the ZIP was built from the current application code: if you edit code after building, rebuild before publishing. It creates a uniquely named `map-…` Release targeting that commit, attaches `energy-network-map.zip`, and includes the project count, snapshot revision and SHA-256 in the release notes. Existing tags are not overwritten. It does not call Luna or embeddings.

Publishing the Release triggers **Deploy prepared project map**. GitHub downloads only that Release asset, checks every file's SHA-256, the snapshot structure and the source fingerprint against the release's code, then uploads and deploys it to Pages. It checks node identities, comparison-row lengths, layout coverage and local-run files. No Python packages, Bun build, local database or OpenAI secret are needed on the runner. The map uses relative asset paths so it works under a repository Pages subfolder.

Check the workflow in **Actions** and the resulting URL in **Settings → Pages**. A Release upload succeeding does not itself confirm that Pages deployment succeeded. Users download the same ZIP from **Releases**, extract it, and follow its `README.txt` to run it with Python 3 and no extra dependencies.

To roll Pages back, open **Actions → Deploy prepared project map → Run workflow** and enter an earlier `map-…` Release tag in `release_tag`. The old ZIP is verified and redeployed. Keep the associated Release asset and tag; editing source alone does not deploy a different dataset.

## All-network expansion and hosting limits

When you are ready to include the whole ENA catalogue, use the explicit scope on all commands:

```sh
.venv/bin/python -m scripts.download_ena --scope all --output data/inbox/ena-all.json
.venv/bin/python -m scripts.update_map data/inbox/ena-all.json --scope all
.venv/bin/python -m scripts.update_map data/inbox/ena-all.json --scope all --apply --live
```

This capability is implemented and covered with multi-owner fixtures; the live saved database has **not** been expanded. Owners, filters and release counts come from the imported entries, without a fixed 320-row limit. The maximum input is 20,000 records, with a 256-column workbook limit. Plan storage, processing time and budget before the 3,200-entry update. Dense comparison rows alone occupy **368,640,000 bytes at 3,200 entries**; the browser fetches a selected row rather than every row. Full-catalogue preparation is local and can take substantially longer than deploying the resulting package.

The builder rejects a public package at 950 MB to leave headroom under GitHub Pages' **1 GB published-site limit**. Pages also has a 10-minute deployment timeout and a soft 100 GB/month bandwidth limit. Its soft 10-builds/hour limit does not apply to custom Actions publishing. Generated snapshots go in **Release assets**, rather than repeatedly adding hundreds of megabytes to Git history. GitHub currently allows individual release assets under 2 GiB. These limits do not guarantee browser performance or adequate bandwidth at every usage level. [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits), [Release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

“All” means the projects currently available from this ENA portal. ENA directs gas innovation projects from 1 January 2025 onwards to the Future Energy Networks portal, so current ENA data alone does not provide complete future gas-network coverage. A separate source adapter would be needed for that. [ENA search/export and coverage notice](https://smarter.energynetworks.org/search-results/).

Workflow setup follows GitHub's [custom Pages workflow guidance](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) and [publishing-source settings](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site). Model calls retain the existing official [Luna Responses API](https://developers.openai.com/api/docs/models/gpt-6-luna) and [embedding API](https://developers.openai.com/api/reference/resources/embeddings/methods/create) workflow. Sources checked 11 October 2026.

## Verification

The map-only repository includes Python tests for graph construction, exports, importing new/changed entries, metadata changes, partial columns, all-network scope, model cache reuse, recovery and verified publishing. Frontend tests cover map colours, hover details, zoom limits and static data decoding. Run the commands in the root README after changes. Tests use fake model and GitHub calls; live publication must also be checked in Actions and at the Pages URL.

The initial snapshot contains 312 projects, checked on 7 October 2026 with financial fields checked on 10 October 2026. The 11 October ENA download contained 313 SPEN projects; preview identified one new entry, requiring one new Luna profile and 14 original-passage embeddings. That newer download was not applied and does not change the initial release's source dates.
