/** 后端 API 封装(开发模式经 Vite 代理,离线模式不可用)。 */

const base = "";

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(base + url, init);
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    return res.json() as Promise<T>;
}

export interface PresetInfo {
    id: string;
    turns: number;
    deck_size: number;
    note: string;
}

export const listPresets = () => fetchJson<{ presets: PresetInfo[] }>("/api/presets");

export interface DeckEntry {
    name: string;
    tier: string;
}

export const fetchPresetDeck = (preset: string) =>
    fetchJson<{ deck: DeckEntry[] }>(`/api/preset-deck?preset=${encodeURIComponent(preset)}`);

export interface TierDetail {
    effect_raw: string;
    source: "master" | "pool" | "";
    stamina_cost: number | null;
    focus_cost: number | null;
}

export interface PoolCard {
    name: string;
    name_zh: string | null;
    rarity: string;
    category: string;
    move: string | null;
    play_trigger: boolean;
    tiers: string[];
    supported: boolean;
    tier_details: Record<string, TierDetail>;
}

export const fetchCards = () => fetchJson<{ cards: PoolCard[] }>("/api/cards");

export interface PItemInfo {
    name: string;
    origin: "idol" | "support";
    trigger: boolean;
    supported: boolean;
    reason: string;
}

export const fetchPitems = () => fetchJson<{ items: PItemInfo[] }>("/api/pitems");

export const fetchTrace = (preset: string, seed: number, strategy: string) =>
    fetchJson<TraceDocument>(`/api/trace?preset=${encodeURIComponent(preset)}&seed=${seed}&strategy=${encodeURIComponent(strategy)}`);

export const fetchDistribution = (preset: string, strategy: string, n: number) =>
    fetchJson<{ preset: string; strategy: string; n: number; scores: number[] }>(
        `/api/distribution?preset=${encodeURIComponent(preset)}&strategy=${encodeURIComponent(strategy)}&n=${n}`,
    );

export interface StatRow {
    strategy: string;
    preset: string;
    n: number;
    mean: number;
    p50: number;
    p90: number;
    win_rate: number;
    mean_ci95?: [number, number];
    p50_ci95?: [number, number];
    win_ci95?: [number, number];
}

export const postSimulate = (body: object) =>
    fetchJson<{ mode: string; stats?: StatRow[]; task_id?: string }>("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });

export const taskStatus = (id: string) => fetchJson<{ status: string; result?: StatRow[]; error?: string }>(`/api/tasks/${id}`);

// ---------------------------------------------------------------------------
// trace 类型(与 agent/hif/roundsim/trace.py 对齐;M-UIb 由 JSON Schema 生成锁定)
// ---------------------------------------------------------------------------

export interface ScoreDetail {
    base_value: number;
    focus_value: number;
    state_mult: number;
    param_mult: number;
    score_up_mult: number;
    bad_mult: number;
    points: number;
    formula: string;
}

export interface ZoneCounts {
    deck: number;
    hand: number;
    grave: number;
    lost: number;
    hold: number;
}

export interface StateSnapshot {
    stamina: number;
    energy: number;
    good_condition_turns: number;
    excellent_condition_turns: number;
    focus: number;
    cards_played: number;
    usable_left: number;
}

export interface TurnTrace {
    turn: number;
    flow: string;
    hand_before: string[];
    drew: string[];
    action: { kind: string; card: string | null; reason: string; illegal: boolean; plays: string[] };
    effects: { tag: string; note: string; detail: string }[];
    triggers: { source: string; note: string }[];
    score: ScoreDetail;
    extra_scores: ScoreDetail[];
    turn_score: number;
    state_after: StateSnapshot;
    zones: ZoneCounts;
    reshuffled: boolean;
}

export interface TraceDocument {
    schema_version: number;
    seed: number;
    strategy: string;
    spec_digest: { preset: string; turns: number; deck_size: number; popular_mode: string; ouenbou: boolean; p_items: string[]; note: string };
    turns: TurnTrace[];
    final: {
        total_score: number;
        final_state: StateSnapshot;
        zones: ZoneCounts;
        reshuffle_count: number;
        opponents: { name: string; score: number }[];
        rank: number;
        won: boolean;
    };
}
