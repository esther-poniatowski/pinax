---
index: "[Pinax documentation](docs/_index.md)"
aliases:
  - Reconciling a folder
---
# Reconciling a folder

A reconciliation maps each file of a folder of references to the Zotero item that holds its work. Where an item lacks its file, or lies outside the collection of the review, the reconciliation changes the library through a verified plan. Finally, the reconciliation exports the citation keys of each folder. Each stage below is one command of Pinax, and the commands exchange their artifacts through the workspace.

*Prerequisites.* The guide assumes three conditions:

- Pinax is installed in an environment that provides Poppler. The Poppler tools `pdftotext` and `pdfinfo` extract the text of the PDFs;
- the Zotero desktop application is running, with Better BibTeX installed when the exports need citation keys;
- a configuration file `pinax.yml` declares the folder, the destination collection and the workspace, as the [configuration reference](configuration.md) specifies.

The option `--config` gives every command the path of the configuration file. The default path is `pinax.yml` in the current directory.

## Reading the library

Matching runs on a fixed state of the library, so the first stage saves a snapshot of it. The probe command prints the versions of Zotero reported by the local API and by the connector:

```sh
pinax probe --config pinax.yml
```

The generated script relies on calls observed with one version of Zotero, so each run must record the version it met. Then, the read command saves every collection and every item, including attachments and trashed items, under the snapshot label `current`. The snapshot also keeps the versions in the file `probe.json`:

```sh
pinax read --config pinax.yml
```

Both commands only read. Pinax refuses a base URL outside the loopback interface, because the local API does not authenticate its readers.

The citation keys of Better BibTeX are pinned: editing a record does not change its key. The keys command lists each item whose key in the snapshot differs from the key reported by Better BibTeX:

```sh
pinax keys --config pinax.yml
```

A key is refreshed by hand in Zotero, through Better BibTeX > Refresh BibTeX key.

## Inventorying the folder

The matching compares the files with the library by content, identifier and title, so each file must first be described. The inventory command records each file with its folder, name and size, and with:

- its SHA-256 and MD5 digests;
- the year that opens its name;
- for a PDF, the first DOI written on its first pages, the text of those pages and its metadata title.

The command reads the folders declared in the configuration file:

```sh
pinax inventory --config pinax.yml
```

Files with identical bytes form one *content*. Matching works on contents, and the exports return to files.

## Matching each content

The matching decides which item holds the work of each content. The match command tries three routes in order for each content, and stops at the first route that yields a candidate item:

1. **Same file.** The library stores an attachment with the same bytes. The candidate is identical by construction.
2. **DOI.** Exactly one item records the DOI found on the first pages.
3. **File name.** The year, an author and the title words of the file name agree with an item. Library records hold empty dates and garbled names, so an item without a plausible year is penalized rather than excluded, and a surname matches by prefix.

A DOI or a title on the first page can belong to a cited work. Therefore, a candidate other than an identical file is *confirmed* only when the opening words of its title, eight by default, appear in sequence in the first pages. When most title words are missing from the pages, the candidate is rejected and the next route is tried.

When no route matches a content, a reverse search looks for library titles in the first page, skipping titles of fewer than four words by default. The title of a file stands at the start of its first page. The search therefore confirms an item when its title starts within the opening window of the page, eighty words by default, and when no other title starts there. A title found later in the page is a citation. The [configuration reference](configuration.md) lists the thresholds.

The match command runs on the snapshot `current` by default:

```sh
pinax match --config pinax.yml
```

The command prints the number of contents in each pair of status and route, such as `matched:doi 12`. The statuses are:

- `matched`: the item holds the work of the file;
- `check`: a candidate is neither identical nor confirmed, for example because the PDF has no text layer;
- `absent`: no item holds the work;
- `preprint-of`: the item holds another version of the work, by manual resolution.

The workspace file `matches.json` records the item, the route and the verdict of each content. The file also records the share of title words found in the pages, and a note naming the rejected candidates and the cited items.

## Resolving the remaining matches

A content left to check needs a decision taken by reading its first page. The resolutions file records each decision once, and every later run of the match command applies it. The example below accepts a candidate left to check, and rejects a candidate proposed for another file:

```yaml
resolutions:
  - file: 2009_smith_model.pdf
    action: accept
  - file: bibliography/review.pdf
    action: reject
    item: ABCD2345
    note: the DOI on page 1 is the DOI of a cited article
```

The [configuration reference](configuration.md) lists the four actions of a resolution. After an edit of the resolutions file, the match command runs again.

## Building the plan

The plan decides every change of the library before any write. The plan command turns the matches into one change plan:

```sh
pinax plan --config pinax.yml
```

The command refuses to plan while a content is still left to check. The plan holds five lists:

- **imports**: each work absent from the library, imported from its largest PDF. Contents sharing a DOI form one work;
- **attachments**: each matched item without a PDF receives the largest matched file;
- **filings**: each matched or preprint item outside the sub-tree of the scope collection is added to the destination collection, and stays in its current collections;
- **corrections**: the record changes declared in the corrections file;
- **skipped**: the works without a PDF file, with the reason.

The plan never creates a collection. When the destination or the scope collection is missing from the snapshot, the command stops, and the researcher creates the collection in Zotero. The command also stops when a corrected item is missing from the snapshot. The command also writes the worklist `worklist.md`. The worklist tables every operation and orders the manual steps of the next stage.

## Applying the plan in Zotero

Zotero retrieves the metadata of a PDF dropped into it, so the imports go through a drop of files. The stage command copies the file of each import into a folder that holds only those files, and verifies each copy against its digest. The option `--open` opens the folder in Finder:

```sh
pinax stage --config pinax.yml --open
```

With the destination collection selected in Zotero, the researcher drags the files of the staged folder into it. The stage command refuses a folder that already holds files, so the drop imports the planned files only.

The other operations go through the generated script. The script command writes it to the file `zotero-script.js` in the workspace:

```sh
pinax script --config pinax.yml
```

The script runs in Zotero under Tools > Developer > Run JavaScript, with "Run as async function" ticked. Before its first write, the script verifies four conditions, and stops at the first failed condition:

- the destination exists under its key and its planned name;
- every item exists outside the trash;
- every file to attach exists;
- every corrected field is valid for its item type.

An attachment or a filing already done is skipped. A correction sets the same values again, and the item stays unchanged. A second run therefore changes nothing. The script returns its action log as JSON. The researcher saves the log to a file, for example `zotero-log.json` in the workspace.

## Checking the library against the plan

The checks compare the plan with a new snapshot, and do not trust the log of the script. The read command saves the state after the change under the label `after`. Then, the check command verifies every operation. The option `--log` also compares the action log with the plan: an operation that the log does not record as done or skipped fails. The commands below assume the log saved in the workspace `.pinax`:

```sh
pinax read --config pinax.yml --snapshot after
pinax check --config pinax.yml --snapshot after --log .pinax/zotero-log.json
```

The command prints each check that did not pass, then a summary, and exits with status 1 when a check failed. Zotero renames an imported file, so the checks locate the file by its content: first by the MD5 that Zotero records, then by hashing the stored files. Every item key follows the merges recorded in the library. The outcomes are:

- `fail`: the operation does not hold, for example in four typical cases:
  - a failed metadata retrieval left an attachment without a parent item;
  - an item lies outside the destination;
  - the title of an item does not open its PDF;
  - an imported item duplicates an existing item;
- `note`: the operation holds with a fact to read, such as a record without a date or a venue, or an item that held another PDF;
- `pass`: the operation holds.

A failure is repaired in Zotero, by a merge or a manual edit, or through the corrections file and a new plan. A new plan replaces the file `plan.json`, so a copy of the applied plan is kept first, since the exports read it. Then, the checks run again on a new snapshot. The full report is saved as the file `check-report.json`.

## Exporting the references

The exports map every file to the item that holds it, once the library is settled. The match command runs again against the settled snapshot. The export command reads the applied plans to recognize the imported files, and its option `--plan` is repeated once per applied plan:

```sh
pinax match --config pinax.yml --snapshot after
pinax export --config pinax.yml --snapshot after --plan .pinax/plan.json
```

The command writes two files to the workspace:

- the evidence table `evidence.tsv` maps each file, by its SHA-256, to its route, its item key and its citation key;
- the reference list `references.yml` lists the citation keys of each folder, and the files left unresolved.

The route of a file takes one of four values:

- `imported`: the file belongs to a work imported by one of the given plans;
- `matched` or `preprint-of`: the match of the file decides its item;
- `unresolved`: no live item with a citation key holds the file.

The option `--header` names a file whose comment block replaces the default header of `references.yml`. In addition, the command prints each citation key carried by several of the exported items. A reference list that cites such a key is ambiguous.
