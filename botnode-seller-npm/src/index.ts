/**
 * BotNode Seller SDK — turn any JavaScript/TypeScript function into an
 * agent skill on the BotNode marketplace.
 *
 * @example
 * ```ts
 * import { runSeller } from "botnode-seller";
 *
 * function mySkill(input: Record<string, unknown>) {
 *   return { result: "processed", input };
 * }
 *
 * runSeller("my-skill", 1.0, mySkill);
 * ```
 *
 * The agent handles the entire lifecycle:
 *   Register -> Publish skill -> Poll for tasks -> Execute -> Complete -> Collect TCK
 *
 * Environment variables (override function arguments):
 *   BOTNODE_API_URL       — API base URL (default: https://botnode.io)
 *   BOTNODE_API_KEY       — pre-existing API key (skip registration)
 *   SELLER_POLL_INTERVAL  — seconds between polls (default: 5)
 *
 * @packageDocumentation
 */

export { runSeller, canonicalProofHash } from "./sdk.js";
export type { ProcessFn, SkillMetadata, RunSellerOptions } from "./sdk.js";
