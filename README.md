# pinax

![Maintenance](https://img.shields.io/maintenance/yes/2026)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)](https://www.python.org/)
[![License: GPL](https://img.shields.io/badge/License-GPL--3.0-yellow.svg)](https://opensource.org/licenses/GPL-3.0)

Reconciles a folder of reference files with a Zotero library and applies verified change plans.

---

## Overview

A literature review leaves folders of PDF files. The work of each file may already lie in a Zotero library, possibly under another file name, without its PDF, or outside the collection of its folder. Pinax maps each file of such a folder to the Zotero item that holds its work, and decides the changes that the library needs. One change plan records these changes:

- the works to import;
- the PDFs to attach to existing items;
- the existing items to add to the collection of their folder;
- the item records to correct.

From the plan, Pinax generates a script for the researcher to run inside Zotero. After the change, Pinax verifies the library against the same plan. Finally, Pinax exports the citation keys of the items that hold the files of each folder.

### Motivation

Matching a folder of references with a library by hand fails in three recurrent ways:

- Zotero renames a file after it retrieves the metadata, and a merge deletes the items that it absorbs. A match recorded by file name or by item key therefore goes stale;
- a digital object identifier (DOI) or a title found on the first page of a PDF often belongs to a cited work. A match by identifier alone then selects the wrong item;
- a batch of manual changes in Zotero leaves no record of the intended state, so the result cannot be checked.

Pinax addresses each failure in turn. First, Pinax identifies every file by its content, and follows the merges recorded in the library. Second, Pinax confirms every candidate item other than an identical stored file by the opening words of its title. Third, Pinax writes nothing without a plan, and checks the library against that plan afterwards.

### Safety

Pinax only reads the library. Every change goes through the generated script, run by the researcher inside Zotero, as the [decision on the change plan](docs/adr/change-plan-contract.md) records.

### Status

Pre-alpha. The stages from the inventory to the exports are implemented and tested on synthetic libraries.

---

## Quick start

A first run on a folder needs a configuration file and the Zotero application running. The configuration file below declares the folder of references and the collection that receives its filed and imported items:

```yaml
sources:
  root: ~/references/review
targets:
  - folder: .
    destination: {path: Review}
```

Every other key takes the value of the defaults shipped with Pinax. The [configuration reference](docs/configuration.md) describes each key, the targets of several folders and the syntaxes of file names.

The commands below run the four stages that precede any change to the library:

```sh
pinax read --config pinax.yml
pinax inventory --config pinax.yml
pinax match --config pinax.yml
pinax plan --config pinax.yml
```

The [guide](docs/guide.md) describes each stage, from this point to the exports.

---

## Documentation

The [documentation index](docs/_index.md) is the entry point.

---

## Contributing

Contributions follow the [contribution guidelines](CONTRIBUTING.md).

---

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
