package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.adapters.ExerciseSessionSnapshotAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.google.gson.GsonBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

/**
 * Mirrors Gson registration on Wear [sendWorkoutHistoryStore] and mobile
 * [com.gabstra.myworkoutassistant.DataLayerListenerService] workoutHistoryGson
 * so polymorphic [SetData] round-trips match the Data Layer JSON contract.
 */
class WorkoutHistoryStoreDataLayerGsonTest {

    private fun dataLayerWorkoutHistoryGson() = GsonBuilder()
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(ExerciseSessionSnapshot::class.java, ExerciseSessionSnapshotAdapter())
        .create()

    @Test
    fun roundTrip_withEnduranceSetData_preservesSetDataType() {
        val gson = dataLayerWorkoutHistoryGson()
        val whId = UUID.randomUUID()
        val workoutId = UUID.randomUUID()
        val workoutHistory = WorkoutHistory(
            id = whId,
            workoutId = workoutId,
            date = LocalDate.of(2024, 6, 1),
            time = LocalTime.of(9, 30),
            startTime = LocalDateTime.of(2024, 6, 1, 9, 30),
            duration = 1200,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID()
        )
        val exerciseId = UUID.randomUUID()
        val setHistory = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = whId,
            exerciseId = exerciseId,
            setId = UUID.randomUUID(),
            order = 0u,
            startTime = LocalDateTime.of(2024, 6, 1, 9, 30),
            endTime = LocalDateTime.of(2024, 6, 1, 9, 40),
            setData = EnduranceSetData(0, 120, true, true, true),
            skipped = false
        )
        val original = WorkoutHistoryStore(
            WorkoutHistory = workoutHistory,
            SetHistories = listOf(setHistory),
            ExerciseInfos = emptyList(),
            WorkoutRecord = null,
            ExerciseSessionProgressions = emptyList()
        )
        val json = gson.toJson(original)
        val parsed = gson.fromJson(json, WorkoutHistoryStore::class.java)
        assertTrue(parsed.SetHistories.single().setData is EnduranceSetData)
        val ed = parsed.SetHistories.single().setData as EnduranceSetData
        assertEquals(120, ed.endTimer)
    }

    @Test
    fun roundTrip_withTimedDurationSetData_preservesSetDataType() {
        val gson = dataLayerWorkoutHistoryGson()
        val whId = UUID.randomUUID()
        val workoutId = UUID.randomUUID()
        val workoutHistory = WorkoutHistory(
            id = whId,
            workoutId = workoutId,
            date = LocalDate.of(2024, 6, 2),
            time = LocalTime.of(10, 0),
            startTime = LocalDateTime.of(2024, 6, 2, 10, 0),
            duration = 600,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID()
        )
        val setHistory = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = whId,
            exerciseId = UUID.randomUUID(),
            setId = UUID.randomUUID(),
            order = 0u,
            startTime = LocalDateTime.of(2024, 6, 2, 10, 0),
            endTime = LocalDateTime.of(2024, 6, 2, 10, 3),
            setData = TimedDurationSetData(0, 90, false, true, false),
            skipped = false
        )
        val original = WorkoutHistoryStore(
            WorkoutHistory = workoutHistory,
            SetHistories = listOf(setHistory),
            ExerciseInfos = emptyList(),
            WorkoutRecord = null,
            ExerciseSessionProgressions = emptyList()
        )
        val json = gson.toJson(original)
        val parsed = gson.fromJson(json, WorkoutHistoryStore::class.java)
        assertTrue(parsed.SetHistories.single().setData is TimedDurationSetData)
        val td = parsed.SetHistories.single().setData as TimedDurationSetData
        assertEquals(90, td.endTimer)
    }
}
