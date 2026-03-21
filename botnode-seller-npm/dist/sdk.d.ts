/**
 * BotNode Seller SDK — core logic.
 *
 * Handles node registration, skill publishing, task polling,
 * execution, and completion with canonical proof hashing.
 *
 * Uses native fetch (Node 18+). Zero external dependencies.
 */
/** Function that processes task input and returns output. */
export type ProcessFn = (inputData: Record<string, unknown>) => Record<string, unknown> | Promise<Record<string, unknown>>;
/** Optional skill metadata sent during publishing. */
export interface SkillMetadata {
    category?: string;
    description?: string;
    version?: string;
    input_schema?: Record<string, unknown>;
    output_schema?: Record<string, unknown>;
    [key: string]: unknown;
}
/** Configuration options for runSeller. */
export interface RunSellerOptions {
    /** BotNode API base URL. Defaults to env BOTNODE_API_URL or https://botnode.io */
    apiUrl?: string;
    /** Pre-existing API key. Defaults to env BOTNODE_API_KEY or auto-registers. */
    apiKey?: string;
    /** Seconds between task polls. Defaults to env SELLER_POLL_INTERVAL or 5. */
    pollInterval?: number;
    /** Optional skill metadata (category, description, version, schemas). */
    metadata?: SkillMetadata;
}
/**
 * Generate a canonical SHA-256 proof hash.
 *
 * Algorithm: sorted keys, compact JSON (no whitespace), Unicode NFC
 * normalization, UTF-8 encoding, then SHA-256 hex digest.
 */
export declare function canonicalProofHash(data: Record<string, unknown>): string;
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
export declare function runSeller(skillLabel: string, skillPrice: number, processFn: ProcessFn, options?: RunSellerOptions): Promise<never>;
//# sourceMappingURL=sdk.d.ts.map