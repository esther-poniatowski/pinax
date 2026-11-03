---
tags:
  - decision
status: proposed
created: 2026-11-03
revised: 2026-11-03
index: "[Architecture decisions](docs/adr/_index.md)"
aliases:
  - Change plan contract decision
---
# Change plan contract

> [!QUESTION] Goal: how does Pinax read a Zotero library, decide which item holds each file, and change the library so that every change can be verified afterwards?

Pinax generalizes a single-use pipeline that reconciled the folders of one literature review with a Zotero library. That pipeline met four constraints of Zotero, observed with Zotero 10.0.6:

- the local API omits the MD5 of many stored attachments, and Zotero renames a PDF after it retrieves the metadata;
- a merge deletes the absorbed items, and the surviving item lists them in its relation `dc:replaces`;
- the connector route `saveItems` ignores its target collection, and no approved local route attaches a file to an existing item or adds an existing item to a collection;
- metadata retrieval on a dropped PDF fails for some documents, such as theses and course handouts, and misreads others.

The present record fixes the access to the library, the identity of a file, the matching, the contract between the stages, and the route of every write.

## Decision

**Read-only access on the loopback interface.** Pinax reads the library through the local API of the desktop application, with GET requests only, and refuses a base URL outside the loopback interface. Pinax reads stored files from the storage directory, and never opens the database file. Two POST requests remain, the connector ping and the Better BibTeX method `item.citationkey`, and neither changes the state of the library. ^read-only

**Identity by content.** A source file is identified by its SHA-256. An attachment is mapped to a file by the MD5 that Zotero records, or else by hashing the stored files whose size equals the size of the file. A file name never identifies a file. Every item key resolves through the `dc:replaces` chains of the library, trashed items included. Therefore, a key recorded before a merge reaches the surviving item. ^content-identity

**Confirmation by the opening words of the title.** The routes of the matching run in a fixed order: same stored file, DOI, file name. A candidate other than an identical file is confirmed only when the first eight words of its title appear in sequence in the first pages of the file. The reverse search accepts a title only when the title starts within the opening window of the first page. A candidate that is neither identical nor confirmed waits for a manual resolution. The resolutions live in a file that every run applies. ^confirmation

**The change plan as the contract.** The plan builder writes one plan, and the script generator reads nothing else. The checks read the same plan back. The builder refuses to plan while a match waits for a resolution. A plan never creates a collection. ^plan-contract

**Writes through a script generated from the plan.** The researcher runs the generated script inside Zotero. The script is assembled from units of one concern each:

- the header, the context and the action log;
- the preflight: it verifies every target before the first write;
- the attachments, the filings and the corrections;
- the result: it returns the log.

An attachment or filing step tests its postcondition first, and skips the write when the postcondition holds. A correction step sets the planned values again, and a corrected item stays unchanged. Therefore, a second run changes nothing. Then, the checks verify every operation against a new snapshot, independently of the log of the script. ^script-route

**Imports through a staged folder.** The stage command copies the file of each work to import into a folder that holds only those files. The researcher drops the files into the destination collection, and Zotero retrieves their metadata. The checks locate each imported file by its content. A file left without a parent item, a record whose title does not open its PDF, and a duplicate each fail a check. ^staged-imports

## Options rejected

Each option below would serve the goal of the record, and one constraint excludes it:

| Option | Constraint that excludes it |
| --- | --- |
| reading the database file | Pinax reads while the application runs, and a database read concurrent with the application can return inconsistent results |
| writing through the Zotero web API | the web API requires credentials, and no approved workflow introduces them |
| writing through the connector `saveItems` | the route ignores its target, and can neither attach a file to an existing item nor file an existing item |
| applying the plan by hand from the worklist only | a manual batch leaves no log, and repeats a step without testing whether the step was already done |
| confirming a match by the share of title words found | a short title of a few common words passes against unrelated pages |
| matching by DOI alone | the DOI on a first page often belongs to a cited article |

## Consequences

The write route holds only while the workflow rules of the researcher approve the generated script as a write route, beside the connector. The status `proposed` of this record holds until those rules are revised.

The script relies on calls observed with Zotero 10.0.6. Each snapshot records the versions of Zotero in its file `probe.json`. A changed version reopens the calls of the script units.

A reconciliation reads the library once before the plan and once after the change. The exports read the applied plans to recognize the imported files. Therefore, a plan file is kept as long as its exports may be rebuilt.
