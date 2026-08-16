<script setup lang="ts">
import { onMounted, ref } from "vue";
import { listPresets, postSimulate, taskStatus, type PresetInfo, type StatRow } from "../api";

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
        let overrides: object | undefined;
        if (overridesJson.value.trim()) overrides = JSON.parse(overridesJson.value);
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
        <div class="row">
            ScenarioSpec 覆盖(JSON 粘贴,可选):
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
