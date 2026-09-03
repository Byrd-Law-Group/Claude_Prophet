#!/usr/bin/env node
// clio-referral-tracker: show / set / report on a matter's referral source,
// stored as a Clio custom field. See ../SKILL.md for usage and behavior.

import axios from "axios";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SKILL_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const API_BASE = (process.env.CLIO_API_BASE || "https://app.clio.com/api/v4").replace(/\/+$/, "");
const TOKEN = process.env.CLIO_ACCESS_TOKEN;
const FIELD_NAME = process.env.CLIO_REFERRAL_FIELD_NAME || "Referral Source";

function fail(message) {
  console.error(`Error: ${message}`);
  process.exit(1);
}

if (!TOKEN) {
  fail(
    "CLIO_ACCESS_TOKEN is not set. Export a valid Clio OAuth2 bearer token before running this skill."
  );
}

const client = axios.create({
  baseURL: API_BASE,
  headers: { Authorization: `Bearer ${TOKEN}` },
});

function loadKnownSources() {
  const p = path.join(SKILL_DIR, "known-sources.json");
  if (!existsSync(p)) return [];
  try {
    const list = JSON.parse(readFileSync(p, "utf8"));
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function parseFromDescription(description, knownSources) {
  if (!description) return null;
  const haystack = description.toLowerCase();
  for (const source of knownSources) {
    if (haystack.includes(String(source).toLowerCase())) return source;
  }
  return null;
}

function toTitleCase(str) {
  return String(str)
    .trim()
    .replace(/\s+/g, " ")
    .replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
}

function slug(str) {
  return String(str).toLowerCase().replace(/[^a-z0-9]/g, "");
}

async function clioGet(urlPath, params) {
  try {
    const res = await client.get(urlPath, { params });
    return res.data;
  } catch (err) {
    const status = err.response?.status;
    const body = err.response?.data ? JSON.stringify(err.response.data) : err.message;
    fail(`Clio API request failed (${urlPath}, HTTP ${status ?? "?"}): ${body}`);
  }
}

async function clioPatch(urlPath, body) {
  try {
    const res = await client.patch(urlPath, body);
    return res.data;
  } catch (err) {
    const status = err.response?.status;
    const body2 = err.response?.data ? JSON.stringify(err.response.data) : err.message;
    fail(`Clio API write failed (${urlPath}, HTTP ${status ?? "?"}): ${body2}`);
  }
}

let referralFieldIdCache = null;
async function getReferralFieldId() {
  if (referralFieldIdCache) return referralFieldIdCache;
  const data = await clioGet("/custom_fields.json", {
    parent_type: "Matter",
    fields: "id,name",
  });
  const match = (data.data || []).find(
    (f) => f.name?.toLowerCase() === FIELD_NAME.toLowerCase()
  );
  if (!match) {
    fail(
      `No Matter custom field named "${FIELD_NAME}" exists in Clio. ` +
        `Create one (Settings > Custom Fields > Matter) or set CLIO_REFERRAL_FIELD_NAME to an existing field.`
    );
  }
  referralFieldIdCache = match.id;
  return match.id;
}

async function findMatter(query) {
  let data = await clioGet("/matters.json", {
    display_number: query,
    fields: "id,display_number,description,status",
  });
  let matches = data.data || [];
  if (matches.length !== 1) {
    data = await clioGet("/matters.json", {
      query,
      fields: "id,display_number,description,status",
    });
    matches = data.data || [];
  }
  if (matches.length === 0) fail(`No matter found matching "${query}".`);
  if (matches.length > 1) {
    const list = matches
      .map((m) => `  ${m.display_number} — ${m.description || "(no description)"} [id ${m.id}]`)
      .join("\n");
    fail(`"${query}" matched ${matches.length} matters, be more specific:\n${list}`);
  }
  return matches[0];
}

function extractCustomFieldValue(matter, fieldId) {
  const cfv = (matter.custom_field_values || []).find(
    (v) => v.custom_field?.id === fieldId
  );
  return cfv ? cfv.value ?? null : null;
}

async function cmdShow(matterQuery) {
  const knownSources = loadKnownSources();
  const matter = await findMatter(matterQuery);
  const fieldId = await getReferralFieldId();
  const full = await clioGet(`/matters/${matter.id}.json`, {
    fields: "id,display_number,description,custom_field_values{id,value,custom_field{id,name}}",
  });
  const explicit = extractCustomFieldValue(full.data, fieldId);
  const parsed = explicit ? null : parseFromDescription(full.data.description, knownSources);
  const source = explicit || parsed;

  console.log(
    JSON.stringify(
      {
        matter_id: full.data.id,
        display_number: full.data.display_number,
        source: source || null,
        source_type: explicit ? "explicit" : parsed ? "parsed" : "unknown_source",
      },
      null,
      2
    )
  );
}

async function cmdSet(matterQuery, source, commit) {
  if (!source) fail("Usage: set <matter> <source> [--commit]");
  const matter = await findMatter(matterQuery);
  const fieldId = await getReferralFieldId();
  const full = await clioGet(`/matters/${matter.id}.json`, {
    fields: "id,display_number,description,custom_field_values{id,value,custom_field{id,name}}",
  });
  const current = extractCustomFieldValue(full.data, fieldId);

  console.log(`Matter:   ${full.data.display_number} (id ${full.data.id})`);
  console.log(`Field:    ${FIELD_NAME}`);
  console.log(`Current:  ${current ?? "(not set)"}`);
  console.log(`New:      ${source}`);

  if (!commit) {
    console.log("\nPreview only — nothing written. Re-run with --commit to save.");
    return;
  }

  await clioPatch(`/matters/${matter.id}.json`, {
    data: { custom_field_values: [{ custom_field: { id: fieldId }, value: source }] },
  });
  console.log("\nSaved.");
}

async function cmdReport(status) {
  const knownSources = loadKnownSources();
  const fieldId = await getReferralFieldId();

  const counts = new Map();
  let unknownCount = 0;
  let scanned = 0;

  let url = "/matters.json";
  let params = {
    status: status === "all" ? undefined : status || "open",
    fields: "id,display_number,description,custom_field_values{id,value,custom_field{id,name}}",
  };

  while (url) {
    const data = await clioGet(url, params);
    for (const matter of data.data || []) {
      scanned += 1;
      const explicit = extractCustomFieldValue(matter, fieldId);
      const parsed = explicit ? null : parseFromDescription(matter.description, knownSources);
      const raw = explicit || parsed;
      if (!raw) {
        unknownCount += 1;
        continue;
      }
      const key = toTitleCase(raw);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    url = data.meta?.paging?.next || null;
    params = undefined; // next link already carries query params
  }

  const ranked = [...counts.entries()]
    .map(([source, count]) => ({ source, count }))
    .sort((a, b) => b.count - a.count);

  const possibleDuplicates = [];
  for (let i = 0; i < ranked.length; i++) {
    for (let j = i + 1; j < ranked.length; j++) {
      const a = slug(ranked[i].source);
      const b = slug(ranked[j].source);
      if (a !== b && (a.startsWith(b) || b.startsWith(a))) {
        possibleDuplicates.push([ranked[i].source, ranked[j].source]);
      }
    }
  }

  console.log(
    JSON.stringify(
      {
        matters_scanned: scanned,
        sources: ranked,
        unknown_source: unknownCount,
        possible_duplicates: possibleDuplicates,
      },
      null,
      2
    )
  );
}

async function main() {
  const [, , cmd, ...rest] = process.argv;
  const commit = rest.includes("--commit");
  const statusArg = rest.find((a) => a.startsWith("--status="));
  const status = statusArg ? statusArg.split("=")[1] : undefined;
  const positional = rest.filter((a) => !a.startsWith("--"));

  switch (cmd) {
    case "show":
      await cmdShow(positional.join(" "));
      break;
    case "set":
      // matter is a single token (display number); everything after it is the source,
      // so a multi-word source doesn't need to be quoted.
      await cmdSet(positional[0], positional.slice(1).join(" "), commit);
      break;
    case "report":
      await cmdReport(status);
      break;
    default:
      fail(
        "Usage:\n" +
          "  node referral-tracker.js show <matter>\n" +
          "  node referral-tracker.js set <matter> <source> [--commit]\n" +
          "  node referral-tracker.js report [--status=open|all]"
      );
  }
}

main();
