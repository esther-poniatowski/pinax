---
tags:
  - decision
status: accepted
created: 2026-11-04
revised: 2026-11-04
index: "[Architecture decisions](docs/adr/_index.md)"
aliases:
  - Consumer configuration decision
---
# Consumer configuration

> [!QUESTION] Goal: how does a consumer adapt Pinax to its own folders, file names, titles and library, without changing the code of Pinax?

Pinax generalizes a pipeline written for one literature review. That pipeline fixed five points in its code, and each point served that review only:

- one destination collection received every filed and imported item;
- the match by name read one syntax of file names, a year, an author and title words separated by underscores;
- the stop words of the match by name were English words;
- the thresholds of the matching were default values of the code;
- the evidence was a tab-separated table, whereas the configuration, the resolutions, the corrections and the reference lists are YAML.

The present record fixes, for each of these points, the key that declares it and the stage that reads it.

## Decision

**Defaults in a shipped file.** The defaults of every optional key live in one file of the package, `defaults.yml`. A null default, as for `staging`, selects a fallback that the configuration reference states. The configuration file of a consumer is merged over the defaults: two mappings are merged key by key, and any other value, a list included, replaces the default. The command `pinax config` prints the merged configuration. The section `matching` holds the thresholds of the matching and the stop words of the match by name. ^shipped-defaults

**Templates for file names.** A consumer declares the syntaxes of its file names as templates, such as `{year}_{title}` or `{authors} - {year} - {title}`, and the match by name tries them in order. The text between two placeholders separates them. The matching parses the names, so the inventory records no part of a name, and a change of the templates needs no new inventory. ^name-templates

**Targets per folder.** Each target assigns a folder of the sources to a destination collection and to a scope. A collection is named by its key or by its path. The plan builder resolves each path against the snapshot, and stops when a path names no collection or several. A file belongs to the target of the deepest folder that contains it. Every filing and every import of the plan records its destination. A drop targets one collection, so the staging folder holds one sub-folder per destination. ^targets

**Evidence as YAML.** The evidence file holds one flow mapping per source, file or record, so that a change of one source changes one line. An unresolved source carries null for its item and its citation key. ^evidence-yaml

## Options rejected

Each option below would serve the goal of the record, and one constraint excludes it:

| Option | Constraint that excludes it |
| --- | --- |
| defaults as values of the fields of the code | a consumer finds a default only by reading the source, and the documentation must repeat each value |
| regular expressions for the syntaxes of file names | each consumer must repeat the pattern of a year and the names of the groups in every expression, whereas a template states a syntax by its separators |
| collections named by key only | the Zotero interface does not show the keys, so the researcher looks each one up |
| collections named by path only | two collections can share one path, and only a key distinguishes them |
| filing an imported work into all its destinations in the same run | the item does not exist before the drop, so the script has no key to file; locating the item by content inside the script would add a search outside the plan |
| keeping the tab-separated evidence table | a consumer would parse a second format, and a table cell cannot distinguish an empty value from an absent one |

## Consequences

The inventory and the plan changed their formats, to `pinax-inventory/2` and `pinax-plan/2`. A stage refuses an artifact of an earlier format, so a workspace written before the change is rebuilt by running its stages again. A plan applied before the change is rebuilt in the new format before the exports read it.

When the files of a work lie under the folders of several destinations, the work is imported into the destination of its imported file. The check of the import reports the other destinations as a note, and the next plan files the item there.

Every stage normalizes words in the same way, and no key of the configuration changes it: Pinax folds accents and case, and drops words shorter than three characters. Therefore, a stop word holds three characters or more, and a surname of two letters never matches by name. Changing that normalization changes the words compared by the matching and the checks, so the change reopens this record.
