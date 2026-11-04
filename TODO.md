# TODO

Items are grouped by the condition that opens them.

## Before relying on the write routes

- [ ] **Observe the changed script units on the current Zotero version.** The units of the generated script were observed with Zotero 10.0.6. The preflight and the filing units changed to address one collection per destination, and the attach unit has not run on Zotero 10.0.7. On the first plan that holds attachments or filings, read the action log and the checks of each unit before relying on the route.
- [ ] **Run `pinax create` on a real library.** The creation through the connector has run against the fake application of the tests only. Its first real run creates one item with `--limit 1`. The researcher reads that item in Zotero, and `pinax check` verifies it, before the command runs without the limit.
- [ ] **Check the item types that hold a DOI.** The builder of connector items, in `src/pinax/records/items.py`, writes the DOI into its own field for journal articles, conference papers and preprints only, and into the field `extra` for every other type. Compare its table `TYPE_FIELDS` with the schema of the running Zotero version, and extend the types that hold a DOI field.

## Open decisions

- [ ] **Create the records described by a DOI only.** The matching reads such records, but the plan skips their creation, since the connector needs metadata. Retrieving their metadata from a registry, such as Crossref, would send the DOIs to an external service. Decide whether Pinax offers this retrieval, as an option that the configuration enables.

## Maintenance

- [ ] **Repair the configuration of the test linter.** The file `config/tools/pylintrc_tests.ini`, inherited from the project template, loads `pytest_pylint` as a plugin of pylint, which it is not. Therefore, pylint stops before reading the tests. Remove the plugin from the configuration, lint the tests once, and decide whether CI lints them.
