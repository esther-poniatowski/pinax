// Mock of the part of the Zotero object model that the generated script calls, for tests.
//
// Usage: node zotero_mock.js <state.json> <script.js> <runs>
// Runs the script <runs> times on the same state, as "Run as async function" would, and prints
// {"runs": [{"log": [...]} | {"error": "..."}], "state": {...}} as JSON.
"use strict";
const fs = require("fs");

const [stateFile, scriptFile, runCount] = process.argv.slice(2);
const state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
const script = fs.readFileSync(scriptFile, "utf8");

// Fields valid for each item type; a type change drops the fields that the new type lacks.
const TYPES = {
  journalArticle: ["title", "date", "DOI", "publicationTitle", "extra", "citationKey"],
  bookSection: ["title", "date", "bookTitle", "extra", "citationKey"],
  thesis: ["title", "date", "university", "thesisType", "extra", "citationKey"],
  attachment: ["title"],
};
const typeNames = Object.keys(TYPES);
const fieldNames = [...new Set(Object.values(TYPES).flat())];

const byId = {};
const byKey = {};
let nextId = 1;
let created = 0;

class Item {
  constructor(key, data) {
    this.id = nextId++;
    this.key = key;
    this.itemType = data.itemType;
    this.fields = { ...(data.fields || {}) };
    this.collections = new Set(data.collections || []);
    this.attachments = [];
    this.creators = data.creators || [];
    this.deleted = Boolean(data.deleted);
    this.attachmentContentType = data.contentType || "";
    this.parentKey = data.parent || null;
    byId[this.id] = this;
    byKey[key] = this;
  }
  getField(name) { return this.fields[name] || ""; }
  setField(name, value) {
    if (!TYPES[this.itemType].includes(name)) throw new Error(`invalid field ${name}`);
    this.fields[name] = value;
  }
  setType(typeID) {
    this.itemType = typeNames[typeID - 1];
    for (const name of Object.keys(this.fields)) {
      if (!TYPES[this.itemType].includes(name)) delete this.fields[name];
    }
  }
  setCreators(creators) { this.creators = creators; }
  getAttachments() { return this.attachments; }
  inCollection(id) { return this.collections.has(id); }
  addToCollection(id) { this.collections.add(id); }
  async saveTx() { return true; }
}

const collections = {};
for (const [key, data] of Object.entries(state.collections)) {
  collections[key] = { id: data.id, key, name: data.name, deleted: Boolean(data.deleted) };
}
for (const [key, data] of Object.entries(state.items)) new Item(key, data);
for (const item of Object.values(byKey)) {
  if (item.parentKey) byKey[item.parentKey].attachments.push(item.id);
}

global.Zotero = {
  Libraries: { userLibraryID: 1 },
  Items: {
    getByLibraryAndKey: (lib, key) => byKey[key] || false,
    get: id => byId[id],
  },
  Collections: { getByLibraryAndKey: (lib, key) => collections[key] || false },
  Attachments: {
    importFromFile: async ({ file, parentItemID }) => {
      created += 1;
      const parent = byId[parentItemID];
      const attachment = new Item(`NEWATT0${created}`, {
        itemType: "attachment", contentType: "application/pdf", parent: parent.key,
        fields: { title: file },
      });
      parent.attachments.push(attachment.id);
      return attachment;
    },
  },
  ItemTypes: { getID: name => typeNames.indexOf(name) + 1 || false },
  ItemFields: {
    getID: name => fieldNames.indexOf(name) + 1 || false,
    isValidForType: (fieldID, typeID) => TYPES[typeNames[typeID - 1]].includes(fieldNames[fieldID - 1]),
  },
};
global.IOUtils = { exists: async path => state.files.includes(path) };

function snapshot() {
  const items = {};
  for (const item of Object.values(byKey)) {
    items[item.key] = {
      itemType: item.itemType, fields: item.fields, creators: item.creators,
      collections: [...item.collections].sort(),
      attachments: item.attachments.map(id => byId[id].key),
    };
  }
  return items;
}

(async () => {
  const runs = [];
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  for (let i = 0; i < Number(runCount); i++) {
    try {
      runs.push({ log: JSON.parse(await new AsyncFunction(script)()) });
    } catch (error) {
      runs.push({ error: String(error.message) });
    }
  }
  process.stdout.write(JSON.stringify({ runs, state: snapshot() }));
})();
