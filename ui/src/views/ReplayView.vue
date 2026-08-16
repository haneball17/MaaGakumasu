<script setup lang="ts">
import { computed, inject, nextTick, onMounted, ref, watch, type Ref } from "vue";
import * as echarts from "echarts";
import { fetchTrace, listPresets, type PresetInfo, type TraceDocument, type TurnTrace } from "../api";

const props = defineProps<{ offline: unknown }>();

const presets = ref<PresetInfo[]>([]);
const preset = ref("hif_r1_rinami");
const seed = ref(42);
const strategy = ref("garakuta_rinami");
const trace = ref<TraceDocument | null>(props.offline as TraceDocument | null);
const turnIdx = ref(1);
const playing = ref(false);
const zoneChart = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;
let timer: number | undefined;

// A/B 视图「代表局回放」跳转注入
const replayRequest = inject<Ref<{ preset: string; seed: number; strategy: string; nonce: number } | null> | null>("replayRequest", null);
watch(
    () => replayRequest?.value?.nonce,
    () => {
        if (!replayRequest?.value) return;
        preset.value = replayRequest.value.preset;
        seed.value = replayRequest.value.seed;
        strategy.value = replayRequest.value.strategy;
        load();
    },
);

const turns = computed(() => trace.value?.turns ?? []);
const cur = computed<TurnTrace | null>(() => turns.value[turnIdx.value - 1] ?? null);

const error = ref("");
const loading = ref(false);

async function load() {
    if (props.offline) return;
    error.value = "";
    loading.value = true;
    try {
        trace.value = await fetchTrace(preset.value, seed.value, strategy.value);
        turnIdx.value = 1;
        await nextTick();
        renderZone();
    } catch (e) {
        error.value = String(e);
    } finally {
        loading.value = false;
    }
}

function renderZone() {
    if (!zoneChart.value || !trace.value) return;
    chart = chart ?? echarts.init(zoneChart.value);
    const ts = trace.value.turns;
    chart.setOption({
        animation: false,
        grid: { top: 24, left: 40, right: 10, bottom: 24 },
        legend: { top: 0, textStyle: { color: "#ccc", fontSize: 11 } },
        xAxis: { type: "category", data: ts.map((t) => `T${t.turn}`), axisLabel: { color: "#aaa" } },
        yAxis: { type: "value", axisLabel: { color: "#aaa" }, splitLine: { lineStyle: { color: "#2a2f36" } } },
        series: [
            { name: "山札", type: "line", data: ts.map((t) => t.zones.deck), smooth: true },
            { name: "捨て札", type: "line", data: ts.map((t) => t.zones.grave), smooth: true },
            { name: "除外(Lost)", type: "line", data: ts.map((t) => t.zones.lost), step: "end" },
        ],
        textStyle: { color: "#ccc" },
    });
}

function play() {
    playing.value = !playing.value;
    if (playing.value) {
        timer = window.setInterval(() => {
            if (turnIdx.value < turns.value.length) turnIdx.value += 1;
            else {
                playing.value = false;
                window.clearInterval(timer);
            }
        }, 900);
    } else if (timer) window.clearInterval(timer);
}

watch(turnIdx, () => {
    if (chart) chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: turnIdx.value - 1 });
});

onMounted(async () => {
    if (!props.offline) {
        try {
            presets.value = (await listPresets()).presets;
        } catch {
            /* 后端未起:离线数据仍可回放 */
        }
    }
    renderZone();
});
</script>

<template>
    <div v-if="!offline" class="card controls">
        预设
        <select v-model="preset">
            <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.id }}({{ p.turns }}T/{{ p.deck_size }}张)</option>
        </select>
        策略
        <select v-model="strategy">
            <option>garakuta_rinami</option>
            <option>greedy</option>
            <option>first_legal</option>
            <option>skip</option>
        </select>
        seed <input v-model.number="seed" type="number" style="width: 80px" />
        <button class="primary" @click="load">{{ loading ? "载入中…" : "载入回放" }}</button>
        <span v-if="error" class="err">{{ error }}</span>
    </div>

    <div v-if="trace" class="card">
        <div class="meta">
            {{ trace.spec_digest.preset || "custom" }} · seed {{ trace.seed }} · {{ trace.strategy }} ·
            総分 <b>{{ trace.final.total_score.toLocaleString() }}</b> · 順位 {{ trace.final.rank }} · 重洗 {{ trace.final.reshuffle_count }} 次
            <span v-for="o in trace.final.opponents" :key="o.name" class="muted">| {{ o.name }} {{ o.score.toLocaleString() }}</span>
        </div>
        <div class="scrubrow">
            <button class="primary" @click="play">{{ playing ? "⏸ 暂停" : "▶ 播放" }}</button>
            <input v-model.number="turnIdx" type="range" min="1" :max="turns.length" class="scrub" />
            <span>T{{ turnIdx }} / {{ turns.length }}</span>
        </div>

        <div v-if="cur" class="turnbox">
            <h3>T{{ cur.turn }} 流行 {{ cur.flow }} · {{ cur.action.kind }}<template v-if="cur.action.card">({{ cur.action.card }})</template></h3>
            <p class="muted">{{ cur.action.reason }}</p>
            <p>
                手牌:<span v-for="(h, i) in cur.hand_before" :key="i" class="chip">{{ h }}</span>
            </p>
            <p class="score">
                得分 <b>{{ cur.turn_score }}</b>
                <span v-if="cur.score.formula" class="muted">{{ cur.score.formula }}</span>
                <span v-for="(x, i) in cur.extra_scores" :key="i" class="muted">+ {{ x.formula }}</span>
            </p>
            <p>
                好調 {{ cur.state_after.good_condition_turns }}T · 絶好調 {{ cur.state_after.excellent_condition_turns }}T · 集中
                {{ cur.state_after.focus }} · 体力 {{ cur.state_after.stamina }} · 元気 {{ cur.state_after.energy }} · 出牌累计
                {{ cur.state_after.cards_played }}
                <span v-if="cur.reshuffled" class="reshuffle">[捨て札重洗]</span>
            </p>
            <p v-if="cur.effects.length" class="muted">效果链:{{ cur.effects.map((e) => `${e.note || e.tag}:${e.detail}`).join("; ") }}</p>
            <p v-if="cur.triggers.length" class="trigger">触发:{{ cur.triggers.map((t) => `${t.source} — ${t.note}`).join("; ") }}</p>
        </div>

        <h3>牌库区演变(压缩过程)</h3>
        <div ref="zoneChart" class="zonechart"></div>

        <h3>回合得分表</h3>
        <table>
            <tr><th>回合</th><th>流</th><th>出牌</th><th>得分</th></tr>
            <tr v-for="t in turns" :key="t.turn" :class="{ cur: t.turn === turnIdx }" @click="turnIdx = t.turn">
                <td>T{{ t.turn }}</td>
                <td>{{ t.flow }}</td>
                <td>{{ t.action.plays.join(", ") || t.action.kind }}</td>
                <td>{{ t.turn_score }}</td>
            </tr>
        </table>
    </div>
</template>

<style scoped>
.controls {
    display: flex;
    align-items: center;
    gap: 10px;
}
.meta {
    color: #9aa4b2;
    margin-bottom: 8px;
}
.scrubrow {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 8px 0;
}
.scrub {
    flex: 1;
}
.turnbox {
    background: #232830;
    border-radius: 8px;
    padding: 10px 14px;
}
.turnbox h3 {
    margin: 4px 0;
    font-size: 15px;
}
.chip {
    background: #2c333d;
    border-radius: 5px;
    padding: 1px 7px;
    margin-right: 4px;
    font-size: 12px;
}
.score b {
    color: #ffd866;
    font-size: 16px;
}
.reshuffle {
    color: #ff7b72;
}
.trigger {
    color: #7ee787;
}
.zonechart {
    height: 220px;
}
tr.cur {
    background: #2d5be3;
    cursor: pointer;
}
</style>
