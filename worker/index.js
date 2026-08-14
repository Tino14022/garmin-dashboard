/**
 * Write path for the training dashboard.
 *
 * The site is static, so it cannot write. This Worker is the one piece that
 * can: the browser POSTs an entry here, and this appends it to the matching
 * data/*.json in the repo via the GitHub Contents API. The next rebuild picks
 * it up like any other logged data.
 *
 * The GitHub token lives only as a Worker secret. The browser never sees it —
 * it holds a separate app token that only authorises calls to this Worker, so
 * a leaked browser token cannot touch the repo directly and is revoked by
 * rotating one secret.
 */

const ENTRY_KINDS = {
  food: {
    file: 'nutrition',
    required: ['date', 'meal', 'description'],
    optional: ['calories', 'protein_g', 'carbs_g', 'fat_g', 'grams'],
    numeric: ['calories', 'protein_g', 'carbs_g', 'fat_g', 'grams'],
  },
  body: {
    file: 'body_comp',
    required: ['date'],
    optional: ['weight_kg', 'body_fat_pct', 'muscle_mass_kg', 'water_pct', 'visceral_fat', 'bmr'],
    numeric: ['weight_kg', 'body_fat_pct', 'muscle_mass_kg', 'water_pct', 'visceral_fat', 'bmr'],
  },
  training: {
    file: 'trainings',
    required: ['date', 'type'],
    optional: ['subtype', 'notes', 'duration_min', 'muscle_groups', 'exercises'],
    numeric: ['duration_min'],
  },
  lifestyle: {
    file: 'lifestyle',
    required: ['date'],
    optional: ['alcohol_units', 'cannabis', 'cigarettes', 'notes'],
    numeric: ['alcohol_units', 'cannabis', 'cigarettes'],
  },
};

const MAX_BODY_BYTES = 16 * 1024;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function cors(env) {
  return {
    'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN || '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '86400',
  };
}

function json(body, status, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...cors(env) },
  });
}

/** Comparison that does not leak the secret's length or contents via timing. */
function secretsMatch(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * Rebuild the entry from the schema instead of trusting what arrived, so no
 * unexpected field can ride along into the repo.
 */
function validate(kind, raw) {
  const schema = ENTRY_KINDS[kind];
  if (!schema) return { error: `unknown kind "${kind}"` };
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { error: 'entry must be an object' };

  const entry = {};
  for (const field of schema.required) {
    const value = raw[field];
    if (value === undefined || value === null || value === '') {
      return { error: `missing required field "${field}"` };
    }
    entry[field] = value;
  }
  for (const field of schema.optional) {
    if (raw[field] !== undefined && raw[field] !== null && raw[field] !== '') {
      entry[field] = raw[field];
    }
  }
  if (!ISO_DATE.test(entry.date)) return { error: 'date must be YYYY-MM-DD' };

  for (const field of schema.numeric) {
    if (entry[field] === undefined) continue;
    const n = Number(entry[field]);
    if (!Number.isFinite(n) || n < 0) return { error: `"${field}" must be a non-negative number` };
    entry[field] = n;
  }
  if (entry.muscle_groups !== undefined) {
    if (typeof entry.muscle_groups !== 'object' || Array.isArray(entry.muscle_groups)) {
      return { error: 'muscle_groups must be an object' };
    }
    for (const [muscle, intensity] of Object.entries(entry.muscle_groups)) {
      const n = Number(intensity);
      if (!Number.isFinite(n) || n < 0 || n > 1) {
        return { error: `muscle_groups.${muscle} must be between 0 and 1` };
      }
    }
  }
  if (entry.exercises !== undefined && !Array.isArray(entry.exercises)) {
    return { error: 'exercises must be an array' };
  }
  return { entry, file: schema.file };
}

function ghHeaders(env) {
  return {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'User-Agent': 'garmin-dashboard-logger',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

async function readFile(env, path) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}?ref=${env.GITHUB_BRANCH || 'master'}`;
  const res = await fetch(url, { headers: ghHeaders(env) });
  if (res.status === 404) return { rows: [], sha: null };
  if (!res.ok) throw new Error(`GitHub read failed (${res.status}): ${await res.text()}`);

  const body = await res.json();
  const decoded = new TextDecoder().decode(
    Uint8Array.from(atob(body.content.replace(/\n/g, '')), (c) => c.charCodeAt(0))
  );
  let rows;
  try {
    rows = JSON.parse(decoded);
  } catch {
    throw new Error(`${path} is not valid JSON; refusing to overwrite it`);
  }
  if (!Array.isArray(rows)) throw new Error(`${path} is not a JSON array`);
  return { rows, sha: body.sha };
}

async function writeFile(env, path, rows, sha, message) {
  const encoded = btoa(
    String.fromCharCode(...new TextEncoder().encode(JSON.stringify(rows, null, 2) + '\n'))
  );
  const res = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`, {
    method: 'PUT',
    headers: { ...ghHeaders(env), 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      content: encoded,
      branch: env.GITHUB_BRANCH || 'master',
      ...(sha ? { sha } : {}),
    }),
  });
  if (res.status === 409) return { conflict: true };
  if (!res.ok) throw new Error(`GitHub write failed (${res.status}): ${await res.text()}`);
  return await res.json();
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(env) });
    if (request.method !== 'POST') return json({ error: 'POST only' }, 405, env);

    for (const required of ['APP_TOKEN', 'GITHUB_TOKEN', 'GITHUB_REPO']) {
      if (!env[required]) return json({ error: `worker is missing ${required}` }, 500, env);
    }

    const auth = request.headers.get('Authorization') || '';
    if (!secretsMatch(auth.replace(/^Bearer\s+/i, ''), env.APP_TOKEN)) {
      return json({ error: 'unauthorized' }, 401, env);
    }

    const raw = await request.text();
    if (raw.length > MAX_BODY_BYTES) return json({ error: 'payload too large' }, 413, env);

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return json({ error: 'body must be JSON' }, 400, env);
    }

    const { entry, file, error } = validate(parsed.kind, parsed.entry);
    if (error) return json({ error }, 400, env);

    const path = `data/${file}.json`;
    const label = entry.description || entry.notes || entry.subtype || parsed.kind;
    const message = `Log ${parsed.kind} for ${entry.date}: ${String(label).slice(0, 72)}`;

    try {
      // One retry covers the case where a scheduled rebuild committed between
      // our read and our write, which would otherwise 409 on a stale sha.
      for (let attempt = 0; attempt < 2; attempt++) {
        const { rows, sha } = await readFile(env, path);
        rows.push(entry);
        const result = await writeFile(env, path, rows, sha, message);
        if (!result.conflict) {
          return json({ ok: true, entry, file: path, commit: result.commit?.sha ?? null }, 200, env);
        }
      }
      return json({ error: 'the file changed while saving; try again' }, 409, env);
    } catch (e) {
      return json({ error: String(e.message || e) }, 502, env);
    }
  },
};
