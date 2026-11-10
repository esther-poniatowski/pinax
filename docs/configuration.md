---
index: "[Pinax documentation](docs/_index.md)"
aliases:
  - Configuration files
---
# Configuration files

A reconciliation reads three YAML files: the configuration file, required, and two optional files of manual decisions. The configuration file is the one given by `--config`; without that option, it is `config/tools/pinax.yml` below the current directory, and otherwise `pinax.yml` in the current directory. A relative path in the configuration file resolves against the directory of that file, never against the current directory: a file in `config/tools/` writes `../../refs` for the folder `refs` of the current directory. The folder of a target is an exception: it is relative to the root of the sources. An unknown key in any of the three files stops the command with an error.

## Configuration file

The configuration file declares where the files lie, which collection receives the items of each folder, and how Pinax reads the files. Only two keys are required: the root of the sources, `sources.root`, and the list `targets`. Every other key takes its value from the [defaults file](../src/pinax/defaults.yml) shipped with Pinax. A key of the configuration file overrides its default. When the file and the defaults both hold a mapping under one key, the two mappings are merged key by key, at every depth. Any other value of the file, such as a list, replaces the default.

The example below reconciles two folders with two collections, reads file names in two syntaxes with a fallback, and overrides two matching keys:

```yaml
sources:
  root: ~/references/review
  names: ["{year}_{title}", "{authors} - {year} - {title}", "{title}"]
targets:
  - folder: reading
    destination: {path: Review/Reading}
  - folder: methods
    destination: {key: EFGH6789}
    scope: {path: Review}
matching:
  title_words: 6
  stop_words: [the, and, for, les, des, une]
resolutions: resolutions.yml
```

The config command validates the configuration file, then prints the configuration in effect: the file merged over the defaults. The printed paths appear as written, before their resolution:

```sh
pinax config --config pinax.yml
```

The table below states the effect of each other key of the defaults file:

| Key | Effect |
| --- | --- |
| `workspace` | directory of the artifacts of every stage |
| `sources.ignore` | exact file names skipped by the inventory, without wildcards |
| `sources.pages` | opening pages whose text is read from each PDF |
| `library.api` | base URL of the Zotero desktop application; only a loopback host is accepted |
| `library.storage` | storage directory of Zotero, holding one sub-directory per attachment key |
| `resolutions` | file of the manual resolutions of matches, described below |
| `corrections` | file of the corrections of item records, described below |
| `staging` | folder receiving the files to import; without a value, the folder `staged/` of the workspace |

## Targets

A target assigns a folder of the sources to the collection that receives its items. Each target holds two required keys and one optional key:

- `folder`: a folder relative to the root, or `.` for the root itself. An absolute path must lie under the root;
- `destination`: the collection that receives the filed, imported and created items of the folder;
- `scope`: optional, the collection whose sub-tree counts as filed: an item in the scope or in one of its descendants receives no filing. Without a scope, the destination is the scope.

Each folder is named by one target only, and a folder cannot climb above the root.

A collection is named either by its eight-character key, `{key: EFGH6789}`, or by its path from the top level, `{path: Review/Reading}`. The plan command resolves each path against the snapshot of the library. The command stops in three cases:

- a key or a path names no collection;
- a path names several collections, and only a key distinguishes them;
- two targets give one destination two different scopes.

A file belongs to the target whose folder is the deepest folder containing the file. Therefore, a target on a sub-folder overrides a target on its parent. The inventory reads only the folders of the targets.

## File-name templates

The match by name reads the year, the authors and the title from the name of a file. The key `sources.names` lists the syntaxes of the names as templates. The match compares the templates, in order, with the whole name without its extension. The first template that matches parses the name. Each template is quoted, since YAML reads a leading `{` as the start of a mapping.

A template combines literal text with three placeholders, each used at most once:

| Placeholder | Matches | Required |
| --- | --- | --- |
| `{year}` | a year from 1500 to 2099, optionally followed by one lower-case letter, as in `2004a` | no |
| `{authors}` | any text, the shortest that lets the rest of the template match | no |
| `{title}` | any text, the shortest that lets the rest of the template match | yes |

The literal text between two placeholders separates them. Thus, the template `{year}_{title}` reads the file name `2004_Smith_attention_model.pdf` as the year 2004 and the title words `Smith attention model`. Without `{authors}`, the match looks for the surnames of an item among the title words.

The default templates are `{year}_{title}` and `{title}`, and the template `{title}` matches any name. A list of templates in the configuration file replaces the default list. When no template of the list matches a name, the match by name skips its file, and the other routes of the matching still apply.

## Record exports

An export of bibliographic records is read as a list of records, not as a reference file. The key `sources.records` lists the patterns of the names of such exports, each with the format of its files. The first pattern matched by a file name, ignoring case, decides the format. Four formats are known:

| Format | Files |
| --- | --- |
| `bibtex` | BibTeX entries, read by a parser of nested braces; a parsing error stops the inventory |
| `ris` | RIS records of tagged lines, each closed by the tag `ER`; an unclosed record, or a line outside any record, stops the inventory |
| `zotero-csv` | the CSV export of Zotero, with the required columns `Item Type` and `Title`; a missing column stops the inventory |
| `doi-list` | one DOI per line; a blank line and a line opening with `#` are skipped, and a line without a DOI stops the inventory |

The default patterns read the files `*.bib` as BibTeX and the files `*.ris` as RIS. A list in the configuration file replaces the default list. Therefore, the example below repeats the default patterns before adding the CSV export and a list of DOIs:

```yaml
sources:
  records:
    - {pattern: "*.bib", format: bibtex}
    - {pattern: "*.ris", format: ris}
    - {pattern: "*.csv", format: zotero-csv}
    - {pattern: "*-dois.txt", format: doi-list}
```

A record belongs to the target of the folder of its export. A record described by a DOI only can be matched, but it cannot be created, since a creation needs metadata.

## Matching thresholds

The section `matching` sets the thresholds of the matching and the stop words of the match by name:

| Key | Effect |
| --- | --- |
| `title_words` | opening title words that must appear in sequence to confirm a candidate |
| `reject_below` | share of title words found in the pages below which a candidate is rejected |
| `name_threshold` | lowest overlap of a file name with an item title for the match by name to propose a candidate |
| `year_tolerance` | largest difference between the year of a file name or of a record and the year of an item |
| `opening_words` | window, in words from the start of the first page, in which the reverse search accepts a title |
| `reverse_min_words` | shortest title, in words, that the reverse search looks for |
| `surname_prefix` | length, in characters, of the shortest surname or file-name word compared by prefix, so that a garbled surname still matches; shorter words must be equal; the match by name and the title route of records use it |
| `undated_penalty` | score removed from a match by name when the year of the name or of the item is unknown |
| `stop_words` | words ignored by the match by name in titles and surnames, such as articles |

Every stage compares words after one normalization: accents and case are folded, and words shorter than three characters are dropped. Therefore, a stop word holds three characters or more, and the configuration refuses a shorter one. For the same reason, a surname of two letters never matches by name, and its file relies on the other routes. When YAML would read a value as a boolean, such as `yes` or `off`, the value is quoted.

## Resolutions file

A resolution records a decision on one content, taken by reading its first page, or on one record work. The match command applies it on every run. The file holds a list under the key `resolutions`, and each entry holds either the key `file` or the key `record`:

```yaml
resolutions:
  - file: 2004_smith_model.pdf   # file name, path relative to the root, or `sha256:<digest>`
    action: reject
    item: ABCD2345
    note: the DOI on page 1 belongs to a cited article
  - record: exports/references.bib#3   # export file and position, or `doi:` or `title:` identity
    action: assign
    item: EFGH6789
```

The identity of a record work appears in the list `records` of the workspace file `matches.json`. A `title:` identity holds the normalized title, made of the words of three letters or more folded in capitals and accents, and the year. For example, the title Shape of Signals of 2001 has the identity `title:shape signals|2001`.

A file name must designate one content only; otherwise, the entry gives the path relative to the root. The four actions are:

| Action | Effect | Item |
| --- | --- | --- |
| `accept` | confirms the candidate left to check | none |
| `reject` | removes the given item from every route, or, without an item, leaves the content or the record work absent; the plan then creates an absent record work | optional |
| `assign` | matches the content to the given item | required |
| `preprint-of` | records that the given item holds another version of the work; the item is filed, but receives no attachment | required |

The match command stops when a resolution names an item absent from the snapshot, or accepts a content or a record work that no route matches.

## Corrections file

A correction changes the record of an existing item, for example after a metadata retrieval took a cover-page line for the title. Another example is a book chapter recorded as a journal article. The plan copies each correction, and the generated script applies it. The file holds a list under the key `corrections`:

```yaml
corrections:
  - item: ABCD2345
    type: bookSection                     # optional new item type
    fields: {date: "2012-03-08"}          # fields set after the type change
    creators:                             # optional, replaces every creator
      - {lastName: Doe, firstName: Jane, creatorType: author}
      - {lastName: Some Institute}        # a creator without first name is one field
    carry: {publicationTitle: bookTitle}  # copied into an empty field of the new type
    preserve: [DOI]                       # kept, or written into `extra` when the new type lacks it
    note: the drop recorded the chapter as a journal article
```

A type change drops the fields that the new type lacks. Therefore, the script reads the fields named by the keys `carry` and `preserve` before the change. A preserved field invalid for the new type is appended to the field `extra` as a line `Name: value`, once. After the change, the check command verifies the type, the fields, the carried and preserved fields, and the last names of the creators.
