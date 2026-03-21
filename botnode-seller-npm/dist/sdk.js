/**
 * BotNode Seller SDK — core logic.
 *
 * Handles node registration, skill publishing, task polling,
 * execution, and completion with canonical proof hashing.
 *
 * Uses native fetch (Node 18+). Zero external dependencies.
 */
import { createHash, randomBytes } from "node:crypto";
// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
function log(level, message) {
    const ts = new Date().toISOString();
    console.log(`${ts} [${level}] ${message}`);
}
// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------
function headers(apiKey) {
    return {
        "X-API-KEY": apiKey,
        "Content-Type": "application/json",
    };
}
async function jsonPost(url, body, hdrs) {
    const res = await fetch(url, {
        method: "POST",
        headers: hdrs ?? { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(30_000),
    });
    const text = await res.text();
    let data;
    try {
        data = JSON.parse(text);
    }
    catch {
        // non-JSON response — leave data undefined
    }
    return { status: res.status, data: data, text };
}
async function jsonGet(url, hdrs) {
    const res = await fetch(url, {
        method: "GET",
        headers: hdrs,
        signal: AbortSignal.timeout(30_000),
    });
    const text = await res.text();
    let data;
    try {
        data = JSON.parse(text);
    }
    catch {
        // non-JSON response
    }
    return { status: res.status, data: data, text };
}
// ---------------------------------------------------------------------------
// Prime check
// ---------------------------------------------------------------------------
/**
 * Trial-division primality test for the registration challenge.
 */
function isPrime(n) {
    if (n < 2)
        return false;
    for (let i = 2, limit = Math.floor(Math.sqrt(n)); i <= limit; i++) {
        if (n % i === 0)
            return false;
    }
    return true;
}
// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------
/**
 * Register a new node by solving the prime-sum challenge.
 * Returns the API key.
 */
async function registerNode(apiUrl) {
    const nodeId = `seller-${randomBytes(6).toString("hex")}`;
    log("INFO", `Registering new node: ${nodeId}`);
    // Step 1: get challenge
    const { status: s1, data: challenge } = await jsonPost(`${apiUrl}/v1/node/register`, { node_id: nodeId });
    if (s1 !== 200 && s1 !== 201) {
        throw new Error(`Registration request failed with status ${s1}`);
    }
    const payload = challenge.verification_challenge.payload;
    // Step 2: solve — sum of primes * 0.5
    const primeSum = payload.filter(isPrime).reduce((a, b) => a + b, 0);
    const solution = primeSum * 0.5;
    log("INFO", `Challenge solved: ${solution}`);
    // Step 3: verify
    const { status: s2, data: verifyData } = await jsonPost(`${apiUrl}/v1/node/verify`, { node_id: nodeId, solution });
    if (s2 !== 200 && s2 !== 201) {
        throw new Error(`Verification failed with status ${s2}`);
    }
    const apiKey = verifyData.api_key;
    log("INFO", `Node registered: ${nodeId} (balance: ${verifyData.unlocked_balance ?? "?"} TCK)`);
    return apiKey;
}
// ---------------------------------------------------------------------------
// Publish
// ---------------------------------------------------------------------------
/**
 * Publish a skill on the marketplace. Returns the skill_id or null on failure.
 */
async function publishSkill(apiUrl, apiKey, skillLabel, skillPrice, metadata) {
    const defaultMeta = {
        category: "custom",
        description: `Seller SDK skill: ${skillLabel}`,
        version: "1.0.0",
    };
    const mergedMeta = { ...defaultMeta, ...metadata };
    const skillDefinition = {
        label: skillLabel,
        price_tck: skillPrice,
        type: "SKILL_OFFER",
        metadata: mergedMeta,
    };
    log("INFO", `Publishing skill: ${skillLabel}`);
    const { status, data } = await jsonPost(`${apiUrl}/v1/marketplace/publish`, skillDefinition, headers(apiKey));
    if (status === 402) {
        log("ERROR", "Insufficient balance to publish (0.50 TCK fee)");
        return null;
    }
    if (status !== 200 && status !== 201) {
        throw new Error(`Publish failed with status ${status}`);
    }
    const skillId = data.skill_id;
    log("INFO", `Skill published: ${skillId}`);
    return skillId;
}
// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------
/**
 * Poll for OPEN tasks assigned to this node.
 */
async function pollTasks(apiUrl, apiKey) {
    const { status, data } = await jsonGet(`${apiUrl}/v1/tasks/mine?status=OPEN`, headers(apiKey));
    if (status !== 200) {
        log("WARN", `Poll failed: ${status}`);
        return [];
    }
    return data?.tasks ?? [];
}
// ---------------------------------------------------------------------------
// Proof hash
// ---------------------------------------------------------------------------
/**
 * Generate a canonical SHA-256 proof hash.
 *
 * Algorithm: sorted keys, compact JSON (no whitespace), Unicode NFC
 * normalization, UTF-8 encoding, then SHA-256 hex digest.
 */
export function canonicalProofHash(data) {
    const serialized = JSON.stringify(data, Object.keys(data).sort());
    // JSON.stringify with a sorted replacer handles only top-level keys.
    // For a fully recursive sort we use a replacer function.
    const deepSorted = JSON.stringify(data, (_key, value) => {
        if (value !== null && typeof value === "object" && !Array.isArray(value)) {
            const sorted = {};
            for (const k of Object.keys(value).sort()) {
                sorted[k] = value[k];
            }
            return sorted;
        }
        return value;
    });
    // NFC normalize
    const normalized = deepSorted.normalize("NFC");
    return createHash("sha256").update(normalized, "utf-8").digest("hex");
}
// ---------------------------------------------------------------------------
// Complete
// ---------------------------------------------------------------------------
/**
 * Submit task output and proof hash to mark a task as completed.
 */
async function completeTask(apiUrl, apiKey, taskId, outputData) {
    const proof = canonicalProofHash(outputData);
    const { status, text } = await jsonPost(`${apiUrl}/v1/tasks/complete`, {
        task_id: taskId,
        output_data: outputData,
        proof_hash: proof,
    }, headers(apiKey));
    if (status === 200) {
        log("INFO", `Task ${taskId} completed — escrow will settle in 24h`);
        return true;
    }
    log("ERROR", `Complete failed for ${taskId}: ${status} ${text.slice(0, 200)}`);
    return false;
}
// ---------------------------------------------------------------------------
// Sleep helper
// ---------------------------------------------------------------------------
function sleep(seconds) {
    return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}
// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------
/**
 * Run a seller agent that publishes a skill and processes tasks indefinitely.
 *
 * @param skillLabel  - Name for the skill on the marketplace.
 * @param skillPrice  - Price in TCK per task execution.
 * @param processFn   - Function that receives input_data and returns an output object.
 *                      May be sync or async.
 * @param options     - Optional overrides for apiUrl, apiKey, pollInterval, and metadata.
 *
 * @example
 * ```ts
 * import { runSeller } from "botnode-seller";
 *
 * runSeller("my-skill", 1.0, async (input) => {
 *   return { result: "processed", input };
 * });
 * ```
 */
export async function runSeller(skillLabel, skillPrice, processFn, options = {}) {
    let apiUrl = options.apiUrl ?? process.env.BOTNODE_API_URL ?? "https://botnode.io";
    let apiKey = options.apiKey ?? process.env.BOTNODE_API_KEY ?? "";
    const pollInterval = options.pollInterval ?? parseInt(process.env.SELLER_POLL_INTERVAL ?? "5", 10);
    // Strip trailing slash from API URL
    apiUrl = apiUrl.replace(/\/+$/, "");
    log("INFO", "============================================================");
    log("INFO", "BotNode Seller Agent starting");
    log("INFO", `API: ${apiUrl}`);
    log("INFO", `Skill: ${skillLabel}`);
    log("INFO", "============================================================");
    // Step 1: Register if no API key
    if (!apiKey) {
        apiKey = await registerNode(apiUrl);
        log("INFO", `Save this API key for next time: ${apiKey}`);
        log("INFO", `  export BOTNODE_API_KEY="${apiKey}"`);
    }
    // Step 2: Publish skill
    const skillId = await publishSkill(apiUrl, apiKey, skillLabel, skillPrice, options.metadata);
    if (!skillId) {
        log("ERROR", "Cannot publish skill — exiting.");
        process.exit(1);
    }
    // Step 3: Poll and execute loop
    log("INFO", `Polling for tasks every ${pollInterval}s... (Ctrl+C to stop)`);
    let completedCount = 0;
    // Handle graceful shutdown
    const shutdown = () => {
        log("INFO", `Stopped. Total tasks completed: ${completedCount}`);
        process.exit(0);
    };
    process.on("SIGINT", shutdown);
    process.on("SIGTERM", shutdown);
    // eslint-disable-next-line no-constant-condition
    while (true) {
        try {
            const tasks = await pollTasks(apiUrl, apiKey);
            for (const task of tasks) {
                const taskId = task.task_id;
                const inputData = task.input_data ?? {};
                log("INFO", `Processing task ${taskId} (skill: ${task.skill_id ?? "?"})`);
                let output;
                try {
                    output = await processFn(inputData);
                }
                catch (err) {
                    const message = err instanceof Error ? err.message : String(err);
                    output = { error: `Skill execution failed: ${message}` };
                    log("ERROR", `processFn() failed: ${message}`);
                }
                if (await completeTask(apiUrl, apiKey, taskId, output)) {
                    completedCount++;
                    log("INFO", `Total tasks completed: ${completedCount}`);
                }
            }
        }
        catch (err) {
            if (err instanceof Error && err.name === "AbortError") {
                // Ctrl+C during fetch — let the signal handler deal with it
                continue;
            }
            const message = err instanceof Error ? err.message : String(err);
            log("ERROR", `Error in poll loop: ${message}`);
        }
        await sleep(pollInterval);
    }
}
//# sourceMappingURL=sdk.js.map