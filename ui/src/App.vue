<script setup lang="ts">
import { provide, ref } from "vue";
import ReplayView from "./views/ReplayView.vue";
import DistributionView from "./views/DistributionView.vue";
import ABView from "./views/ABView.vue";

defineProps<{ offlineTrace: unknown }>();

const tab = ref<"replay" | "dist" | "ab">("replay");
const tabs = [
    { id: "replay", label: "单局回放" },
    { id: "dist", label: "批量分布" },
    { id: "ab", label: "A/B 对比" },
] as const;

// A/B → 回放跳转(代表局):注入共享状态,ReplayView 监听并自动载入
const replayRequest = ref<{ preset: string; seed: number; strategy: string; nonce: number } | null>(null);
provide("replayRequest", replayRequest);

function jumpReplay(preset: string, seed: number, strategy: string) {
    replayRequest.value = { preset, seed, strategy, nonce: Date.now() };
    tab.value = "replay";
}
</script>

<template>
    <header class="bar">
        <h1>HIF Round 模拟器</h1>
        <nav>
            <button v-for="t in tabs" :key="t.id" :class="{ active: tab === t.id }" @click="tab = t.id">{{ t.label }}</button>
        </nav>
    </header>
    <main :class="{ offline: !!offlineTrace }">
        <ReplayView v-show="tab === 'replay'" :offline="offlineTrace" />
        <DistributionView v-show="tab === 'dist' && !offlineTrace" />
        <ABView v-show="tab === 'ab' && !offlineTrace" @jump-replay="jumpReplay" />
        <p v-if="offlineTrace" class="offline-note">离线降级模式:仅单局回放可用(其余视图需后端)。</p>
    </main>
</template>

<style>
body {
    margin: 0;
    font-family: system-ui, "Segoe UI", sans-serif;
    background: #14161a;
    color: #e6e6e6;
}
.bar {
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 10px 20px;
    background: #1c2026;
}
.bar h1 {
    font-size: 17px;
    margin: 0;
}
.bar nav button {
    background: transparent;
    border: 1px solid #3a4048;
    color: #ccc;
    border-radius: 6px;
    padding: 6px 14px;
    margin-right: 8px;
    cursor: pointer;
}
.bar nav button.active {
    background: #2d5be3;
    border-color: #2d5be3;
    color: #fff;
}
main {
    padding: 16px 20px;
    max-width: 1080px;
    margin: 0 auto;
}
.card {
    background: #1c2026;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 14px;
}
.muted {
    color: #9aa4b2;
    font-size: 13px;
}
select,
input {
    background: #23272e;
    color: #e6e6e6;
    border: 1px solid #3a4048;
    border-radius: 6px;
    padding: 5px 8px;
}
button.primary {
    background: #2d5be3;
    border: none;
    color: #fff;
    border-radius: 6px;
    padding: 7px 16px;
    cursor: pointer;
}
.offline-note {
    color: #ffd866;
}
table {
    border-collapse: collapse;
    font-size: 13px;
    width: 100%;
}
td,
th {
    border: 1px solid #333a44;
    padding: 4px 8px;
    text-align: left;
}
</style>
