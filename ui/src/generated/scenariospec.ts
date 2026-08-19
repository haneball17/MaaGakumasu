// 由 tools/export_roundsim_schema.py 从 pydantic 模型生成——不要手改;改模型后重新导出。
export interface CardInDeck {
    name: string;
    tier?: string;
}

export interface ExamSettings {
    turns?: number;
    turn_start_distribute?: number;
    hand_limit?: number;
    hold_limit?: number;
    stamina_recover_per_turn_end?: number;
}

export interface FixedPopular {
    mode?: string;
    turns: unknown[];
}

export interface InitialExamState {
    stamina?: number;
    max_stamina?: number;
    energy?: number;
    params?: ParamsSnapshot;
    p_drinks?: Record<string, unknown>;
    good_condition_turns?: number;
    excellent_condition_turns?: number;
    focus?: number;
}

export interface J3RandomPopular {
    mode?: string;
    criteria?: Record<string, unknown>;
    first_weights?: Record<string, unknown>;
}

export interface OpponentSpec {
    name: string;
    score_min: number;
    score_max: number;
}

export interface PItems {
    ouenbou?: boolean;
    items?: unknown[];
}

export interface ParamsSnapshot {
    vocal?: number;
    dance?: number;
    visual?: number;
}

export interface Scenario {
    deck: unknown[];
    initial?: InitialExamState;
    p_items?: PItems;
    popular_mode: unknown;
    first_hand?: unknown[];
}

export interface ScenarioSpec {
    scenario: Scenario;
    exam_settings?: ExamSettings;
    opponent?: unknown[];
    note?: string;
}
