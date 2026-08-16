<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as echarts from "echarts";
import { fetchDistribution, listPresets, type PresetInfo } from "../api";

const presets = ref<PresetInfo[]>([]);
const preset = ref("hif_r1_rinami");
const strategy = ref("garakuta_rinami");
const n = ref(100);
const scores = ref<number[]>([]);
const summary = ref<string>("");
const histEl = ref<HTMLDivElement | null>(null);
const boxEl = ref<HTMLDivElement | null>(null);

function stats(list: number[]) {
    const s = [...list].sort((a, b) => a - b);
    const q = (p: number) => s[Math.min(s.length - 1, Math.floor(s.length * p))];
    const mean = s.reduce((a, b) => a + b, 0) / s.length;
    return { p10: q(0.1), p50: q(0.5), p90: q(0.9), mean: Math.round(mean) };
}

async function load() {
    const res = await fetchDistribution(preset.value, strategy.value, n.value);
    scores.value = res.scores;
    const st = stats(res.scores);
    summary.value = `N=${res.n} 均值 ${st.mean.toLocaleString()} · P10 ${st.p10.toLocaleString()} · P50 ${st.p50.toLocaleString()} · P90 ${st.p90.toLocaleString()}`;
    render();
}

function render() {
    if (!histEl.value) return;
    const chart = echarts.init(histEl.value);
    chart.setOption({
        grid: { top: 20, left: 60, right: 20, bottom: 40 },
        tooltip: {},
        xAxis: { type: "value", name: "得分", axisLabel: { color: "#aaa" } },
        yAxis: { type: "value", name: "局数", axisLabel: { color: "#aaa" } },
        series: [{ type: "bar", data: scores.value, barCategoryGap: "0%", itemStyle: { color: "#2d5be3" } }],
        textStyle: { color: "#ccc" },
    });
    if (boxEl.value) {
        echarts.init(boxEl.value).setOption({
            grid: { top: 10, left: 60, right: 20, bottom: 30 },
            xAxis: { type: "category", data: [strategy.value], axisLabel: { color: "#aaa" } },
            yAxis: { type: "value", axisLabel: { color: "#aaa" } },
            series: [{ type: "boxplot", data: [[stats(scores.value).p10, stats(scores.value).p50, stats(scores.value).p90]], itemStyle: { color: "#1f6feb55" } }],
        });
    }
}

onMounted(async () => {
    presets.value = (await listPresets()).presets;
});
</script>

<template>
    <div class="card controls">
        预设
        <select v-model="preset">
            <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.id }}</option>
        </select>
        策略
        <select v-model="strategy">
            <option>garakuta_rinami</option>
            <option>greedy</option>
            <option>first_legal</option>
        </select>
        N <input v-model.number="n" type="number" min="1" max="200" style="width: 70px" />
        <button class="primary" @click="load">跑分布</button>
        <span class="muted">{{ summary }}</span>
    </div>
    <div class="card">
        <h3>得分直方图</h3>
        <div ref="histEl" class="chart"></div>
    </div>
    <div class="card">
        <h3>箱线图</h3>
        <div ref="boxEl" class="chart small"></div>
    </div>
</template>

<style scoped>
.controls {
    display: flex;
    align-items: center;
    gap: 10px;
}
.chart {
    height: 320px;
}
.chart.small {
    height: 220px;
}
</style>
