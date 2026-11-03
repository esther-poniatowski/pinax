---
index: "[Pinax documentation](docs/_index.md)"
aliases:
  - Configuration files
---
# Configuration files

A reconciliation reads three YAML files: the configuration file, required, and two optional files of manual decisions. A relative path in the configuration file resolves against the directory of that file, never against the current directory. An unknown key in any of the three files stops the command with an error.

## Configuration file

The configuration file declares where the files lie, which collection receives the items, and where the artifacts go. The file holds two required sections, `sources` and `library`, and five optional keys. The example below sets every key:

```yaml
workspace: .pinax                # directory of the artifacts; default `.pinax`
sources:
  root: ~/references/review      # required
  folders: [bibliography1, bibliography2]   # default: every file under the root
  ignore: [.DS_Store]            # default: [.DS_Store]
  pages: 2                       # opening pages read from each PDF; default 2
library:
  destination: ABCD2345          # required: key of the collection receiving items
  scope: EFGH6789                # collection whose sub-tree counts as filed; default: destination
  api: http://127.0.0.1:23119    # loopback only; default shown
  storage: ~/Zotero/storage      # default shown
matching:
  title_words: 8
  reject_below: 0.5
  name_threshold: 0.5
  year_tolerance: 1
  opening_words: 80
  reverse_min_words: 4
resolutions: resolutions.yml     # optional
corrections: corrections.yml     # optional
staging: staged                  # resolves against this file; default: `staged/` in the workspace
```

The collection keys are the eight-character keys of the local API. The scope collection lets a review collection with sub-collections count as one destination: an item anywhere in the sub-tree of the scope is not filed again.

The section `matching` sets the thresholds of the matching:

| Key | Effect | Default |
| --- | --- | --- |
| `title_words` | opening title words that must appear in sequence to confirm a candidate | 8 |
| `reject_below` | share of title words found in the pages below which a candidate is rejected | 0.5 |
| `name_threshold` | lowest overlap between file-name words and title words for a match by name | 0.5 |
| `year_tolerance` | largest difference between the year of a file name and the year of an item | 1 |
| `opening_words` | window, in words from the start of the first page, in which the reverse search accepts a title | 80 |
| `reverse_min_words` | shortest title, in words, that the reverse search looks for | 4 |

## Resolutions file

A resolution records a decision on one content, taken by reading its first page. The match command applies it on every run. The file holds a list under the key `resolutions`:

```yaml
resolutions:
  - file: 2004_smith_model.pdf   # file name, path relative to the root, or `sha256:<digest>`
    action: reject
    item: ABCD2345
    note: the DOI on page 1 belongs to a cited article
```

A file name must designate one content only; otherwise, the entry gives the path relative to the root. The four actions are:

| Action | Effect | Item |
| --- | --- | --- |
| `accept` | confirms the candidate left to check | none |
| `reject` | removes the given item from every route, or, without an item, leaves the content absent | optional |
| `assign` | matches the content to the given item | required |
| `preprint-of` | records that the given item holds another version of the work; the item is filed, but receives no attachment | required |

The match command stops when a resolution names an item absent from the snapshot, or accepts a content that no route matches.

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
