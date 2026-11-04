---
tags:
  - decision
status: accepted
created: 2026-11-04
revised: 2026-11-04
index: "[Architecture decisions](docs/adr/_index.md)"
aliases:
  - Bibliographic records decision
---
# Bibliographic records

> [!QUESTION] Goal: how does Pinax reconcile references that exist only as bibliographic records, without a file, and create an item for each record work missing from the library?

A source folder can hold record exports, such as BibTeX, RIS or the CSV export of Zotero, and lists of DOIs. Before this record, Pinax read every file of a folder as a reference file, so an export counted as one unmatched file. A reconciliation of such records by hand-written scripts exposed five defects:

- two records of one export shared one key while naming two works;
- a split of the entries at the first closing brace cut short the entries with a field spanning several lines;
- the BibTeX importer of Zotero skipped two entries of a batch and reported nothing;
- a key held a letter outside ASCII;
- a record without DOI differed from its item only in the capitalization of its title.

The present record fixes the definition of a record, its readers, its identity, its matching, its creation and its checks.

## Decision

**A record as a source.** The key `sources.records` lists file patterns, each with the format of its files. A file matching a pattern is read as an export of records, and is not a reference file of its own. A record is identified by its export file and its position in that file, never by its key, so two records sharing one key stay two records. A record belongs to the target of the folder of its export file. ^record-source

**Parsers by format.** BibTeX is parsed by the library `bibtexparser`. The library reads nested braces and fields spanning several lines. RIS is a format of tagged lines, read line by line. The CSV export of Zotero is read by the `csv` module of the standard library, with its named columns. A list of DOIs holds one DOI per line. ^parsers

**Identity of a work.** The identity of a record is its normalized DOI, or else its normalized title and its year. The normalization folds capitals and accents, so a title differing only in capitalization keeps its identity. Records sharing one identity form one work, also across several exports of the same records. Those records must agree on their title and their year; otherwise, the work waits for a resolution. ^record-identity

**Match routes.** When exactly one live item records the DOI of a work, the work is matched to it if the title of the item equals the title of the record. When no live item records the DOI, the work is matched by its normalized title, its year within the tolerance, and its first author. When one test refutes the candidate, or when several candidates qualify, the work is left to check. A resolution names a record by its export file and its position, or a work by its identity. ^record-match

**Creations in the plan.** The plan lists one creation for each work that no item holds. A creation carries the item to create, built from the record that holds the most fields, and the destination of its target. A field invalid for the item type is written into the field `extra` as `Name: value`, as a correction preserves a field. When only a DOI describes a work, the work is skipped, since a creation needs metadata. An absent PDF holds the work of a creation when its pages confirm the record's title, or when it carries the record's DOI and its pages do not reject that title. The plan does not import such a PDF, so one work yields one item, and the next plan attaches the PDF to the created item. ^record-creations

**Creation through the connector.** The command `pinax create` creates the items of the plan through the connector, and it is the only command of Pinax that writes to the library. The connector ignores the target of the endpoint `saveItems`, and the endpoint `updateSession` retargets only the last item of a session. Therefore, the command follows a serial transaction, one item per session:

1. the command probes the connector, and reads the numeric identifier of each destination from the list of targets;
2. the command searches the library for the identity of the item, and skips an item already present;
3. the command posts the item to the endpoint `saveItems`, then retargets the session to the destination through the endpoint `updateSession`;
4. the command reads the item back through the local API, and verifies its identity, its title, its collection and its uniqueness.

The command stops at the first failed verification and at the first ambiguous outcome. The command writes its log after each item, and the option `--limit` bounds the number of items created in one run. A second run could miss an item saved under another title, so a run that follows a failed or ambiguous outcome waits for the option `--reconciled`. ^connector-creation

**Checks and exports.** The checks verify that each creation yields one live item with the identity of its work, in its destination, under the title of its record. The evidence lists the records beside the files, each with its export file, its position, its key and its item. The reference list of a folder includes the citation keys of its records. ^record-checks

## Options rejected

Each option below would serve the goal of the record, and one constraint excludes it:

| Option | Constraint that excludes it |
| --- | --- |
| identifying a record by its key | two records of one export can share a key |
| splitting a BibTeX export into entries by its lines | a field can span several lines and close on a line of its own |
| merging the records of several exports | the exports can disagree, and a merge would hide the disagreement |
| staging an import file for the researcher | the collection of the items imported by Zotero is not verified, and its importer skipped entries without report |
| writing the missing DOIs for an import by identifier | records without a DOI would be left out |
| creating a work held by a record and a PDF from the PDF | metadata retrieval on a PDF misreads some documents, whereas the record states the metadata |

## Consequences

Pinax no longer only reads the library: the command `pinax create` writes, and every other command still reads only. The researcher reviews the plan and its worklist before a creation, as before a run of the generated script.

The connector behaviour relied on was observed with Zotero 10.0.6, and the list of targets with Zotero 10.0.7. A changed version reopens the transaction of `pinax create`.

The inventory, the matches and the plan change their formats, to `pinax-inventory/3`, `pinax-matches/2` and `pinax-plan/3`, and the evidence lists the files under the key `files` and the records under the key `records`.
