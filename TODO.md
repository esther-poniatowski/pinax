# TODO

Items are grouped by the condition that opens them.

## Before relying on the write routes

- [ ] **Observe the attach unit on the current Zotero version.** The preflight and the filing units ran on Zotero 10.0.7, on a plan of four filings, and `pinax check` passed each filing. The attach unit has not run on Zotero 10.0.7. On the first plan that holds attachments, read the action log and the checks of the unit before relying on it.
- [ ] **Run `pinax create` on a real library.** The creation through the connector has run against the fake application of the tests only. Its first real run creates one item with `--limit 1`. The researcher reads that item in Zotero, and `pinax check` verifies it, before the command runs without the limit.
- [ ] **Check the item types that hold a DOI.** The builder of connector items, in `src/pinax/records/items.py`, writes the DOI into its own field for journal articles, conference papers and preprints only, and into the field `extra` for every other type. Compare its table `TYPE_FIELDS` with the schema of the running Zotero version, and extend the types that hold a DOI field.

## Open decisions

- [ ] **Create the records described by a DOI only.** The matching reads such records, but the plan skips their creation, since the connector needs metadata. Retrieving their metadata from a registry, such as Crossref, would send the DOIs to an external service. Decide whether Pinax offers this retrieval, as an option that the configuration enables.

## Write route

- [ ] **Apply the plans through a Zotero plugin.** The researcher chose to replace the pasted script by a plugin, kept in this repository, which runs the operations of an approved plan inside Zotero when Pinax calls it on the loopback interface. Three conditions precede its use. The Zotero workflow rule of oikos must admit the route, since it admits only the pasted script today. The plugin must refuse a caller other than Pinax, since the loopback interface authenticates no caller. Each release of Zotero must be checked against the plugin. The plugin would also give two repairs that the script lacks: creating the parent item of a standalone attachment, and attaching a second file to an item that already holds one.

## Maintenance

- [ ] **Repair the configuration of the test linter.** The file `config/tools/pylintrc_tests.ini`, inherited from the project template, loads `pytest_pylint` as a plugin of pylint, which it is not. Therefore, pylint stops before reading the tests. Remove the plugin from the configuration, lint the tests once, and decide whether CI lints them.
