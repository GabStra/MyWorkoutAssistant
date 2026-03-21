package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.time.LocalDateTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ExerciseSessionSnapshotTest {
    @Test
    fun `buildExerciseSessionSnapshot preserves middle inserted rest ordering`() {
        val set1Id = UUID.randomUUID()
        val insertedRestId = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        val currentSets: List<Set> = listOf(
            WeightSet(id = set1Id, reps = 5, weight = 80.0),
            RestSet(id = insertedRestId, timeInSeconds = 90),
            WeightSet(id = set2Id, reps = 5, weight = 85.0)
        )
        val setHistories = listOf(
            setHistory(set1Id, 0u, WeightSetData(actualReps = 5, actualWeight = 82.5, volume = 412.5)),
            setHistory(insertedRestId, 1u, RestSetData(startTimer = 90, endTimer = 70)),
            setHistory(set2Id, 2u, WeightSetData(actualReps = 6, actualWeight = 87.5, volume = 525.0))
        )

        val snapshot = buildExerciseSessionSnapshot(currentSets, setHistories)

        assertEquals(listOf(set1Id, insertedRestId, set2Id), snapshot.sets.map { it.setId })
        assertTrue(snapshot.sets[1].set is RestSet)
        assertFalse((snapshot.sets[1].set as RestSet).shouldReapplyHistoryToSet)
        assertEquals(87.5, (snapshot.sets[2].set as WeightSet).weight, 0.0)
        assertEquals(6, (snapshot.sets[2].set as WeightSet).reps)
    }

    @Test
    fun `buildExerciseSessionSnapshot preserves middle inserted rest and set ordering`() {
        val set1Id = UUID.randomUUID()
        val insertedRestId = UUID.randomUUID()
        val insertedSetId = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        val currentSets: List<Set> = listOf(
            WeightSet(id = set1Id, reps = 5, weight = 80.0),
            RestSet(id = insertedRestId, timeInSeconds = 90),
            WeightSet(id = insertedSetId, reps = 5, weight = 80.0),
            WeightSet(id = set2Id, reps = 5, weight = 85.0)
        )
        val setHistories = listOf(
            setHistory(set1Id, 0u, WeightSetData(actualReps = 5, actualWeight = 82.5, volume = 412.5)),
            setHistory(insertedRestId, 1u, RestSetData(startTimer = 90, endTimer = 70)),
            setHistory(insertedSetId, 2u, WeightSetData(actualReps = 4, actualWeight = 82.5, volume = 330.0)),
            setHistory(set2Id, 3u, WeightSetData(actualReps = 6, actualWeight = 87.5, volume = 525.0))
        )

        val snapshot = buildExerciseSessionSnapshot(currentSets, setHistories)

        assertEquals(listOf(set1Id, insertedRestId, insertedSetId, set2Id), snapshot.sets.map { it.setId })
        assertTrue(snapshot.sets[1].set is RestSet)
        assertTrue(snapshot.sets[2].set is WeightSet)
        assertEquals(82.5, (snapshot.sets[2].set as WeightSet).weight, 0.0)
        assertEquals(4, (snapshot.sets[2].set as WeightSet).reps)
    }

    @Test
    fun `buildExerciseSessionSnapshot excludes rest pause sets from persisted structure`() {
        val set1Id = UUID.randomUUID()
        val restPauseRestId = UUID.randomUUID()
        val restPauseSetId = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        val currentSets: List<Set> = listOf(
            WeightSet(id = set1Id, reps = 5, weight = 80.0),
            RestSet(id = restPauseRestId, timeInSeconds = 30, subCategory = SetSubCategory.RestPauseSet),
            WeightSet(id = restPauseSetId, reps = 3, weight = 80.0, subCategory = SetSubCategory.RestPauseSet),
            WeightSet(id = set2Id, reps = 5, weight = 85.0)
        )
        val setHistories = listOf(
            setHistory(set1Id, 0u, WeightSetData(actualReps = 5, actualWeight = 80.0, volume = 400.0)),
            setHistory(
                restPauseRestId,
                1u,
                RestSetData(startTimer = 30, endTimer = 20, subCategory = SetSubCategory.RestPauseSet)
            ),
            setHistory(
                restPauseSetId,
                2u,
                WeightSetData(actualReps = 3, actualWeight = 80.0, volume = 240.0, subCategory = SetSubCategory.RestPauseSet)
            ),
            setHistory(set2Id, 3u, WeightSetData(actualReps = 5, actualWeight = 85.0, volume = 425.0))
        )

        val snapshot = buildExerciseSessionSnapshot(currentSets, setHistories)

        assertEquals(listOf(set1Id, set2Id), snapshot.sets.map { it.setId })
        assertFalse(snapshot.toSets().any { isTemporarySessionOnlySet(it) })
    }

    @Test
    fun `legacy set history snapshot conversion keeps rest data and execution metrics`() {
        val setId = UUID.randomUUID()
        val restId = UUID.randomUUID()
        val snapshot = exerciseSessionSnapshotFromLegacySetHistories(
            listOf(
                setHistory(setId, 0u, WeightSetData(actualReps = 8, actualWeight = 100.0, volume = 800.0)),
                setHistory(restId, 1u, RestSetData(startTimer = 90, endTimer = 70))
            )
        )

        assertEquals(listOf(setId, restId), snapshot.sets.map { it.setId })
        assertEquals(1, snapshot.toExecutedSimpleSets().size)
        assertTrue(snapshot.sets[1].set is RestSet)
        assertFalse((snapshot.sets[1].set as RestSet).shouldReapplyHistoryToSet)
    }

    private fun setHistory(setId: UUID, order: UInt, setData: com.gabstra.myworkoutassistant.shared.setdata.SetData): SetHistory {
        return SetHistory(
            id = UUID.randomUUID(),
            setId = setId,
            order = order,
            startTime = LocalDateTime.now(),
            endTime = LocalDateTime.now(),
            setData = setData,
            skipped = false
        )
    }
}
