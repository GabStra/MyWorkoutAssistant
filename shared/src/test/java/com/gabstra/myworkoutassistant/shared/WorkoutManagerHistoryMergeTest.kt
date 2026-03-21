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

class WorkoutManagerHistoryMergeTest {
    @Test
    fun `mergeExerciseSetsFromHistory keeps programmed rest and appends trailing historical sets`() {
        val workSetId = UUID.randomUUID()
        val restSetId = UUID.randomUUID()
        val trailingRestSetId = UUID.randomUUID()

        val originalSets: List<Set> = listOf(
            WeightSet(id = workSetId, reps = 8, weight = 100.0),
            RestSet(id = restSetId, timeInSeconds = 90, shouldReapplyHistoryToSet = false)
        )
        val setHistories = listOf(
            SetHistory(
                id = UUID.randomUUID(),
                setId = workSetId,
                order = 0u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = WeightSetData(actualReps = 10, actualWeight = 105.0, volume = 1050.0),
                skipped = false
            ),
            SetHistory(
                id = UUID.randomUUID(),
                setId = restSetId,
                order = 1u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = RestSetData(startTimer = 45, endTimer = 30),
                skipped = false
            ),
            SetHistory(
                id = UUID.randomUUID(),
                setId = trailingRestSetId,
                order = 2u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = RestSetData(startTimer = 60, endTimer = 40),
                skipped = false
            )
        )

        val merged = WorkoutManager.mergeExerciseSetsFromHistory(originalSets, setHistories)

        assertEquals(3, merged.size)
        assertEquals(105.0, (merged[0] as WeightSet).weight, 0.0)
        assertEquals(10, (merged[0] as WeightSet).reps)
        assertEquals(90, (merged[1] as RestSet).timeInSeconds)
        assertFalse((merged[1] as RestSet).shouldReapplyHistoryToSet)
        assertEquals(60, (merged[2] as RestSet).timeInSeconds)
        assertFalse((merged[2] as RestSet).shouldReapplyHistoryToSet)
    }

    @Test
    fun `mergeExerciseSetsFromHistory keeps inserted middle rest and set in executed order`() {
        val firstSetId = UUID.randomUUID()
        val secondSetId = UUID.randomUUID()
        val insertedRestSetId = UUID.randomUUID()
        val insertedSetId = UUID.randomUUID()

        val originalSets: List<Set> = listOf(
            WeightSet(id = firstSetId, reps = 5, weight = 80.0),
            WeightSet(id = secondSetId, reps = 5, weight = 85.0)
        )
        val setHistories = listOf(
            SetHistory(
                id = UUID.randomUUID(),
                setId = firstSetId,
                order = 0u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = WeightSetData(actualReps = 5, actualWeight = 82.5, volume = 412.5),
                skipped = false
            ),
            SetHistory(
                id = UUID.randomUUID(),
                setId = insertedRestSetId,
                order = 1u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = RestSetData(startTimer = 90, endTimer = 70),
                skipped = false
            ),
            SetHistory(
                id = UUID.randomUUID(),
                setId = insertedSetId,
                order = 2u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = WeightSetData(actualReps = 4, actualWeight = 82.5, volume = 330.0),
                skipped = false
            ),
            SetHistory(
                id = UUID.randomUUID(),
                setId = secondSetId,
                order = 3u,
                startTime = LocalDateTime.now(),
                endTime = LocalDateTime.now(),
                setData = WeightSetData(actualReps = 6, actualWeight = 87.5, volume = 525.0),
                skipped = false
            )
        )

        val merged = WorkoutManager.mergeExerciseSetsFromHistory(originalSets, setHistories)

        assertEquals(listOf(firstSetId, insertedRestSetId, insertedSetId, secondSetId), merged.map { it.id })
        assertTrue(merged[1] is RestSet)
        assertFalse((merged[1] as RestSet).shouldReapplyHistoryToSet)
        assertTrue(merged[2] is WeightSet)
        assertEquals(82.5, (merged[2] as WeightSet).weight, 0.0)
        assertEquals(4, (merged[2] as WeightSet).reps)
    }

    @Test
    fun `applySetHistoryToProgrammedSet respects shouldReapplyHistoryToSet`() {
        val restSet = RestSet(
            id = UUID.randomUUID(),
            timeInSeconds = 120,
            shouldReapplyHistoryToSet = false
        )
        val history = SetHistory(
            id = UUID.randomUUID(),
            setId = restSet.id,
            order = 0u,
            startTime = LocalDateTime.now(),
            endTime = LocalDateTime.now(),
            setData = RestSetData(startTimer = 30, endTimer = 20, subCategory = SetSubCategory.WorkSet),
            skipped = false
        )

        val resolved = applySetHistoryToProgrammedSet(restSet, history)

        assertTrue(resolved is RestSet)
        assertEquals(120, (resolved as RestSet).timeInSeconds)
    }
}
