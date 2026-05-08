package com.gabstra.myworkoutassistant.e2e.fixtures

import java.util.UUID

object ResumeCrossDeviceSyncSpec {
    const val WORKOUT_NAME = "A - Squat/Bench"

    val WORKOUT_ID: UUID = UUID.fromString("efdba35b-82bf-418e-9362-4ffa2d39e435")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("63c3379f-f734-424c-94e5-05af28a945f8")
    val INCOMPLETE_HISTORY_ID: UUID = UUID.fromString("9b67898a-febe-4c09-9d4e-830cff9ca864")

    val BACK_SQUAT_EXERCISE_ID: UUID = UUID.fromString("fc5ff3fe-8128-49b0-a9c6-95ab4f42c488")
    val BENCH_EXERCISE_ID: UUID = UUID.fromString("c8c032e6-af76-4ae7-b1fd-ebe037bc05a3")
    val PULLUPS_EXERCISE_ID: UUID = UUID.fromString("018b4cc4-2698-4855-97de-801200bb0d43")
    val ROW_EXERCISE_ID: UUID = UUID.fromString("6ca47933-c90e-4a41-ba94-13114c1de8e1")

    val SEEDED_EXERCISE_EXACT_COUNTS: Map<UUID, Int> = linkedMapOf(
        BACK_SQUAT_EXERCISE_ID to 6,
        BENCH_EXERCISE_ID to 6,
        PULLUPS_EXERCISE_ID to 3,
        ROW_EXERCISE_ID to 3
    )
}
