<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { fetchCards, fetchPitems, fetchPresetDeck, listPresets, postSimulate, taskStatus, type DeckEntry, type PItemInfo, type PoolCard, type PresetInfo, type StatRow } from "../api";

const emit = defineEmits<{ (e: "jump-replay", preset: string, seed: number, strategy: string): void }>();

const presets = ref<PresetInfo[]>([]);
const preset = ref("hif_r1_rinami");
const strategies = ref<string[]>(["garakuta_rinami"]);
const allStrategies = ["garakuta_rinami", "greedy", "first_legal"];
const n = ref(100);
const seed0 = ref(0);
const combined = ref(false);
const overridesJson = ref("");
const advancedOpen = ref(false);
const busy = ref(false);
const stats = ref<StatRow[]>([]);
const error = ref("");
const assumptions = ref<string[]>([]);
let pollTimer: number | undefined;

// -- 卡组编辑器(M-UIb 标准表单:预设 + 搜索增删 + JSON 粘贴三通道) --
const deckEntries = ref<DeckEntry[]>([]);
const deckDirty = ref(false);
const cardPool = ref<PoolCard[]>([]);
const deckSearch = ref("");
const searchResults = computed(() => {
    const q = deckSearch.value.trim();
    if (!q) return [];
    return cardPool.value.filter((c) => c.name.includes(q)).slice(0, 8);
});

async function loadDeck(p: string) {
    deckEntries.value = (await fetchPresetDeck(p)).deck;
    deckDirty.value = false;
}

function addCard(card: PoolCard) {
    deckEntries.value.push({ name: card.name, tier: card.tiers[0] ?? "無印" });
    deckDirty.value = true;
    deckSearch.value = "";
}

function removeCard(idx: number) {
    deckEntries.value.splice(idx, 1);
    deckDirty.value = true;
}

watch(preset, (p) => {
    if (!deckDirty.value) loadDeck(p);
});

// -- 效果预览(Item A):搜索行内嵌文本 + 卡组 chip 点击弹详情 --
const TIER_ORDER = ["無印", "+", "++", "+++"];
const detail = ref<PoolCard | null>(null);

function tierSortKey(t: string) {
    const i = TIER_ORDER.indexOf(t);
    return i < 0 ? TIER_ORDER.length : i;
}

function openDetail(name: string) {
    detail.value = cardPool.value.find((c) => c.name === name) ?? null;
}

function previewTier(c: PoolCard): string | null {
    return TIER_ORDER.find((t) => c.tier_details[t]?.effect_raw) ?? c.tiers.find((t) => c.tier_details[t]?.effect_raw) ?? null;
}

function previewText(c: PoolCard): string {
    const t = previewTier(c);
    return t ? `[${t}] ${c.tier_details[t].effect_raw}` : "";
}

// -- P item 编辑(Item B:确定列表 R2-3;数据驱动,未建模件标红禁选) --
const pitems = ref<PItemInfo[]>([]);
const selectedPItems = ref<string[]>([]);
const pitemSearch = ref("");
const pitemResults = computed(() => {
    const q = pitemSearch.value.trim();
    if (!q) return [];
    return pitems.value.filter((p) => p.name.includes(q) && p.supported).slice(0, 6);
});

function addPItem(name: string) {
    if (!selectedPItems.value.includes(name)) selectedPItems.value.push(name);
    pitemSearch.value = "";
}

function removePItem(idx: number) {
    selectedPItems.value.splice(idx, 1);
}

function isSynth(c: PoolCard): boolean {
    const t = previewTier(c);
    return !!t && c.tier_details[t].source === "pool";
}

function toggleStrategy(s: string) {
    const i = strategies.value.indexOf(s);
    if (i >= 0) strategies.value.splice(i, 1);
    else strategies.value.push(s);
}

async function run() {
    busy.value = true;
    error.value = "";
    stats.value = [];
    try {
        let overrides: Record<string, unknown> | undefined;
        if (overridesJson.value.trim()) overrides = JSON.parse(overridesJson.value);
        if (deckDirty.value) {
            // 编辑器是 scenario.deck 的真源;JSON 粘贴仍可覆盖其他字段
            overrides = { ...(overrides ?? {}), scenario: { ...(overrides?.scenario ?? {}), deck: deckEntries.value } };
        }
        if (selectedPItems.value.length) {
            const scen = { ...(overrides?.scenario ?? {}) } as Record<string, unknown>;
            overrides = {
                ...overrides,
                scenario: { ...scen, p_items: { ...(scen.p_items ?? {}), items: selectedPItems.value } },
            };
        }
        const res = await postSimulate({
            preset: preset.value,
            overrides,
            strategies: strategies.value.length ? strategies.value : ["garakuta_rinami"],
            n: n.value,
            seed0: seed0.value,
            combined: combined.value,
            async_run: n.value > 200,
        });
        if (res.mode === "sync") {
            stats.value = res.stats ?? [];
            busy.value = false;
        } else if (res.task_id) {
            pollTimer = window.setInterval(async () => {
                const t = await taskStatus(res.task_id!);
                if (t.status === "done") {
                    stats.value = t.result ?? [];
                    stopPoll();
                } else if (t.status === "error" || t.status === "cancelled") {
                    error.value = t.error || t.status;
                    stopPoll();
                }
            }, 1200);
        }
    } catch (e) {
        error.value = String(e);
        busy.value = false;
    }
}

function stopPoll() {
    if (pollTimer) window.clearInterval(pollTimer);
    busy.value = false;
}

onMounted(async () => {
    presets.value = (await listPresets()).presets;
    cardPool.value = (await fetchCards()).cards;
    pitems.value = (await fetchPitems()).items;
    await loadDeck(preset.value);
});
</script>

<template>
    <div class="card controls">
        <b>快速预设</b>
        <select v-model="preset">
            <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.id }}({{ p.turns }}T)</option>
        </select>
        <label><input v-model="combined" type="checkbox" /> 優勝组合模式(R1+R2)</label>
    </div>

    <div class="card">
        <b>标准表单</b>
        <div class="row">
            策略对比:
            <label v-for="s in allStrategies" :key="s">
                <input type="checkbox" :checked="strategies.includes(s)" @change="toggleStrategy(s)" /> {{ s }}
            </label>
        </div>
        <div class="row">
            N <input v-model.number="n" type="number" min="1" style="width: 80px" />
            seed0 <input v-model.number="seed0" type="number" style="width: 90px" />
        </div>
        <div class="deckeditor">
            <b>卡组编辑</b>({{ deckEntries.length }} 张{{ deckDirty ? " · 已修改" : "" }})
            <div class="decklist">
                <span v-for="(c, i) in deckEntries" :key="i" class="chip chipclick" @click="openDetail(c.name)">
                    {{ c.name }}{{ c.tier === "無印" ? "" : c.tier }} <a href="#" @click.stop.prevent="removeCard(i)">×</a>
                </span>
            </div>
            <div class="row">
                搜索添加:<input v-model="deckSearch" placeholder="卡名(流派池 122 张,点击卡名看详情)" style="width: 220px" />
            </div>
            <ul v-if="searchResults.length" class="results">
                <li v-for="c in searchResults" :key="c.name" :class="{ unsup: !c.supported }">
                    <div class="hitmain">
                        <span class="cname">{{ c.name }}<i v-if="c.name_zh" class="zh">({{ c.name_zh }})</i></span>
                        <span class="muted">{{ c.rarity }} · {{ c.move === "Lost" ? "除外" : "循环" }}{{ c.play_trigger ? " · 有使用门槛" : "" }}{{ c.supported ? "" : " · ⚠ 未建模,加入会预检失败" }}</span>
                        <div v-if="previewText(c)" class="fx" :class="{ synth: isSynth(c) }">{{ previewText(c) }}</div>
                    </div>
                    <button class="primary small" :disabled="!c.supported" @click="addCard(c)">添加</button>
                </li>
            </ul>
        </div>
        <div class="pitemeditor">
            <b>P item 携带</b>(确定列表{{ selectedPItems.length ? " · 已修改" : "" }})
            <div class="decklist" v-if="selectedPItems.length">
                <span v-for="(n, i) in selectedPItems" :key="n" class="chip">
                    {{ n }} <a href="#" @click.prevent="removePItem(i)">×</a>
                </span>
            </div>
            <div v-else class="muted" style="margin: 6px 0">空 = 跟随预设(莉波 = 憧れ続けた輝き)</div>
            <div class="row">
                添加:<input v-model="pitemSearch" placeholder="道具名(收录 153 件;未建模件禁选)" style="width: 220px" />
            </div>
            <ul v-if="pitemResults.length" class="results">
                <li v-for="p in pitemResults" :key="p.name">
                    <span class="cname">{{ p.name }}</span>
                    <span class="muted">{{ p.origin === "idol" ? "偶像卡" : "支援卡" }} · {{ p.reason || "trigger 型(计数间隔+好調门槛)" }}</span>
                    <button class="primary small" :disabled="selectedPItems.includes(p.name)" @click="addPItem(p.name)">
                        {{ selectedPItems.includes(p.name) ? "已选" : "添加" }}
                    </button>
                </li>
            </ul>
        </div>
        <div class="row">
            其他覆盖(JSON 粘贴,可选):
            <textarea v-model="overridesJson" rows="2" placeholder='{"scenario":{"initial":{"stamina":20}}}'></textarea>
        </div>
        <button class="primary" :disabled="busy" @click="run">{{ busy ? "运行中…" : "一键模拟" }}</button>
        <span v-if="error" class="err">{{ error }}</span>
    </div>

    <div class="card">
        <a href="#" @click.prevent="advancedOpen = !advancedOpen">{{ advancedOpen ? "▾" : "▸" }} 高级(结构参数/対手区间经 JSON 覆盖)</a>
        <div v-show="advancedOpen" class="muted">
            exam_settings 与 opponent 的覆盖同样走上方 JSON 粘贴框,如
            <code>{"exam_settings":{"turns":12},"opponent":[{"name":"自定义","score_min":300000,"score_max":400000}]}</code
            >;schema 见 <code>/api/schema</code>。
        </div>
    </div>

    <div v-if="stats.length" class="card">
        <h3>A/B 结果(CRN 同批种子)</h3>
        <table>
            <tr>
                <th>策略</th>
                <th>N</th>
                <th>均值</th>
                <th>P50</th>
                <th>P90</th>
                <th>勝率</th>
                <th>mean 95%CI</th>
                <th>代表局</th>
            </tr>
            <tr v-for="s in stats" :key="s.strategy">
                <td>{{ s.strategy }}</td>
                <td>{{ s.n }}</td>
                <td>{{ s.mean.toLocaleString() }}</td>
                <td>{{ s.p50.toLocaleString() }}</td>
                <td>{{ s.p90.toLocaleString() }}</td>
                <td>{{ (s.win_rate * 100).toFixed(1) }}%</td>
                <td v-if="s.mean_ci95">{{ s.mean_ci95[0].toLocaleString() }}~{{ s.mean_ci95[1].toLocaleString() }}</td>
                <td>
                    <a
                        href="#"
                        @click.prevent="emit('jump-replay', preset, seed0, s.strategy)"
                        >回放 seed={{ seed0 }}</a
                    >
                </td>
            </tr>
        </table>
    </div>
    <div v-if="detail" class="overlay" @click.self="detail = null">
        <div class="detailcard">
            <header>
                <b>{{ detail.name }}</b>
                <span v-if="detail.name_zh" class="zh">{{ detail.name_zh }}</span>
                <span class="muted">{{ detail.rarity }} · {{ detail.move === "Lost" ? "除外" : "循环" }}{{ detail.supported ? "" : " · ⚠ 未建模" }}</span>
                <a href="#" class="close" @click.prevent="detail = null">×</a>
            </header>
            <table>
                <tr v-for="t in detail.tiers.slice().sort((a, b) => tierSortKey(a) - tierSortKey(b))" :key="t">
                    <th>{{ t }}</th>
                    <td class="cost">体力{{ detail.tier_details[t]?.stamina_cost ?? "?" }}</td>
                    <td :class="{ synth: detail.tier_details[t]?.source === 'pool' }">
                        {{ detail.tier_details[t]?.effect_raw || "(无效果数据)" }}
                    </td>
                </tr>
            </table>
        </div>
    </div>
</template>

<style scoped>
.controls {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}
.row {
    margin: 8px 0;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}
.deckeditor {
    margin: 10px 0;
    padding: 10px;
    background: #191d23;
    border-radius: 8px;
}
.pitemeditor {
    margin: 10px 0;
    padding: 10px;
    background: #191d23;
    border-radius: 8px;
}
.decklist {
    margin: 8px 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.chip {
    background: #2c333d;
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 12px;
}
.chip.chipclick {
    cursor: pointer;
}
.chip.chipclick:hover {
    background: #3a4450;
}
.chip a {
    color: #ff7b72;
    text-decoration: none;
    margin-left: 4px;
}
.results {
    list-style: none;
    padding: 0;
    margin: 6px 0;
    max-height: 220px;
    overflow-y: auto;
}
.results li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    border-bottom: 1px solid #2a2f36;
}
.results li.unsup {
    color: #ff9d8f;
}
.hitmain {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
}
.cname {
    white-space: nowrap;
}
.zh {
    color: #8b949e;
    font-size: 12px;
    font-style: normal;
    margin-left: 2px;
}
.fx {
    flex-basis: 100%;
    color: #c9d1d9;
    font-size: 12px;
}
.fx.synth {
    color: #8b949e;
    font-style: italic;
}
.overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
}
.detailcard {
    background: #191d23;
    border: 1px solid #3a4048;
    border-radius: 10px;
    padding: 14px 18px;
    max-width: 560px;
    width: min(92vw, 560px);
    max-height: 80vh;
    overflow-y: auto;
}
.detailcard header {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 8px;
}
.detailcard .close {
    margin-left: auto;
    color: #ff7b72;
    text-decoration: none;
    font-size: 16px;
}
.detailcard .cost {
    white-space: nowrap;
    color: #8b949e;
    font-size: 12px;
}
.detailcard td.synth {
    color: #8b949e;
    font-style: italic;
}
button.small {
    padding: 2px 10px;
    font-size: 12px;
}
textarea {
    width: 100%;
    background: #23272e;
    color: #e6e6e6;
    border: 1px solid #3a4048;
    border-radius: 6px;
    font-family: monospace;
}
.err {
    color: #ff7b72;
}
code {
    background: #23272e;
    padding: 1px 5px;
    border-radius: 4px;
}
</style>
