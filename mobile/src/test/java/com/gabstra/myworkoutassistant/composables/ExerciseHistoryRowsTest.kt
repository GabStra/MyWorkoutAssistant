package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class ExerciseHistoryRowsTest {
    @Test
    fun `buildExerciseHistoryRows preserves rest rows and unilateral side identifiers`() {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Dumbbell Curl",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            intraSetRestInSeconds = 5,
        )
        val workoutHistoryId = UUID.randomUUID()
        val start = LocalDateTime.of(2026, 4, 30, 10, 0, 0)
        val setHistories = listOf(
            buildWeightSetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                setId = setId,
                start = start,
                executionSequence = 0u,
            )
        )
        val restHistories = listOf(
            buildRestHistory(
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                start = start.plusSeconds(20),
                executionSequence = 1u,
            )
        )

        val rows = buildExerciseHistoryRows(
            exercise = exercise,
            equipment = null,
            setHistories = setHistories,
            intraExerciseRestHistories = restHistories,
            showRest = true,
        )

        assertEquals(
            listOf(
                SetTableRowUiModel.Data(
                    identifier = "1-L",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Rest("REST 00:05 elapsed"),
                SetTableRowUiModel.Data(
                    identifier = "1-R",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
            ),
            rows
        )
    }

    @Test
    fun `buildExerciseHistoryRows keeps unilateral numbering grouped by logical set`() {
        val exerciseId = UUID.randomUUID()
        val firstSetId = UUID.randomUUID()
        val secondSetId = UUID.randomUUID()
        val workoutHistoryId = UUID.randomUUID()
        val start = LocalDateTime.of(2026, 4, 30, 10, 0, 0)

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Single Arm Row",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            intraSetRestInSeconds = 5,
        )
        val setHistories = listOf(
            buildWeightSetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                setId = firstSetId,
                start = start,
                executionSequence = 0u,
            ),
            buildWeightSetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                setId = secondSetId,
                start = start.plusSeconds(60),
                executionSequence = 2u,
            ),
        )
        val restHistories = listOf(
            buildRestHistory(
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                start = start.plusSeconds(20),
                executionSequence = 1u,
                plannedRestSeconds = 30,
            ),
        )

        val rows = buildExerciseHistoryRows(
            exercise = exercise,
            equipment = null,
            setHistories = setHistories,
            intraExerciseRestHistories = restHistories,
            showRest = true,
        )

        assertEquals(
            listOf(
                SetTableRowUiModel.Data(
                    identifier = "1-L",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Rest("REST 00:30 elapsed"),
                SetTableRowUiModel.Data(
                    identifier = "1-R",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Data(
                    identifier = "2-L",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Data(
                    identifier = "2-R",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
            ),
            rows
        )
    }

    @Test
    fun `buildExerciseHistoryRows keeps warmup single row and duplicates work set`() {
        val exerciseId = UUID.randomUUID()
        val warmupSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val workoutHistoryId = UUID.randomUUID()
        val start = LocalDateTime.of(2026, 4, 30, 10, 0, 0)

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Single Arm Press",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            intraSetRestInSeconds = 5,
        )
        val setHistories = listOf(
            buildWeightSetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                setId = warmupSetId,
                start = start,
                executionSequence = 0u,
                subCategory = SetSubCategory.WarmupSet,
            ),
            buildWeightSetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                setId = workSetId,
                start = start.plusSeconds(30),
                executionSequence = 1u,
            ),
        )

        val rows = buildExerciseHistoryRows(
            exercise = exercise,
            equipment = null,
            setHistories = setHistories,
            intraExerciseRestHistories = emptyList(),
            showRest = true,
        )

        assertEquals(
            listOf(
                SetTableRowUiModel.Data(
                    identifier = "W1",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Data(
                    identifier = "1-L",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Data(
                    identifier = "1-R",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
            ),
            rows
        )
    }

    @Test
    fun `buildExerciseTemplateRows duplicates unilateral work sets with intra set rest`() {
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Single Arm Press",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            intraSetRestInSeconds = 5,
        )
        val rows = buildExerciseTemplateRows(
            sets = listOf(
                WeightSet(
                    id = UUID.randomUUID(),
                    reps = 8,
                    weight = 10.0,
                    subCategory = SetSubCategory.WarmupSet,
                ),
                WeightSet(
                    id = UUID.randomUUID(),
                    reps = 10,
                    weight = 12.0,
                    subCategory = SetSubCategory.WorkSet,
                ),
            ),
            exercise = exercise,
            equipment = null,
        )

        assertEquals(
            listOf(
                SetTableRowUiModel.Data(
                    identifier = "W1",
                    primaryValue = "10.0 kg",
                    secondaryValue = "8",
                ),
                SetTableRowUiModel.Data(
                    identifier = "1-L",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
                SetTableRowUiModel.Rest("REST 00:05"),
                SetTableRowUiModel.Data(
                    identifier = "1-R",
                    primaryValue = "12.0 kg",
                    secondaryValue = "10",
                ),
            ),
            rows
        )
    }

    @Test
    fun `buildExerciseTemplatePreviewItems returns single data item for bodyweight set without intra set rest`() {
        val setId = UUID.randomUUID()
        val exercise = buildTemplateExercise(intraSetRestInSeconds = null)

        val previewItems = buildExerciseTemplatePreviewItems(
            sets = listOf(
                BodyWeightSet(
                    id = setId,
                    reps = 12,
                    additionalWeight = 0.0,
                    subCategory = SetSubCategory.WorkSet,
                )
            ),
            exercise = exercise,
            equipment = null,
        )

        assertEquals(
            listOf(
                SetPreviewItemUiModel(
                    setId = setId,
                    rows = listOf(
                        SetTableRowUiModel.Data(
                            identifier = "1",
                            primaryValue = "BW",
                            secondaryValue = "12",
                        )
                    ),
                )
            ),
            previewItems
        )
    }

    @Test
    fun `buildExerciseTemplatePreviewItems returns single rest item for rest set`() {
        val setId = UUID.randomUUID()
        val exercise = buildTemplateExercise(intraSetRestInSeconds = 5)

        val previewItems = buildExerciseTemplatePreviewItems(
            sets = listOf(
                RestSet(
                    id = setId,
                    timeInSeconds = 30,
                )
            ),
            exercise = exercise,
            equipment = null,
        )

        assertEquals(
            listOf(
                SetPreviewItemUiModel(
                    setId = setId,
                    rows = listOf(SetTableRowUiModel.Rest("REST 00:30")),
                )
            ),
            previewItems
        )
    }

    @Test
    fun `buildExerciseTemplatePreviewItems groups unilateral work set with rest row`() {
        val setId = UUID.randomUUID()
        val exercise = buildTemplateExercise(intraSetRestInSeconds = 5)

        val previewItems = buildExerciseTemplatePreviewItems(
            sets = listOf(
                WeightSet(
                    id = setId,
                    reps = 10,
                    weight = 12.0,
                    subCategory = SetSubCategory.WorkSet,
                )
            ),
            exercise = exercise,
            equipment = null,
        )

        assertEquals(
            listOf(
                SetPreviewItemUiModel(
                    setId = setId,
                    rows = listOf(
                        SetTableRowUiModel.Data(
                            identifier = "1-L",
                            primaryValue = "12.0 kg",
                            secondaryValue = "10",
                        ),
                        SetTableRowUiModel.Rest("REST 00:05"),
                        SetTableRowUiModel.Data(
                            identifier = "1-R",
                            primaryValue = "12.0 kg",
                            secondaryValue = "10",
                        ),
                    ),
                    usesDashedContainer = true,
                    isGroupedUnilateral = true,
                )
            ),
            previewItems
        )
    }

    @Test
    fun `buildExerciseTemplatePreviewItems keeps unilateral warmup as one row`() {
        val setId = UUID.randomUUID()
        val exercise = buildTemplateExercise(intraSetRestInSeconds = 5)

        val previewItems = buildExerciseTemplatePreviewItems(
            sets = listOf(
                WeightSet(
                    id = setId,
                    reps = 8,
                    weight = 10.0,
                    subCategory = SetSubCategory.WarmupSet,
                )
            ),
            exercise = exercise,
            equipment = null,
        )

        assertEquals(
            listOf(
                SetPreviewItemUiModel(
                    setId = setId,
                    rows = listOf(
                        SetTableRowUiModel.Data(
                            identifier = "W1",
                            primaryValue = "10.0 kg",
                            secondaryValue = "8",
                        )
                    ),
                )
            ),
            previewItems
        )
    }

    @Test
    fun `buildExerciseTemplatePreviewItems keeps unilateral work set flat without intra set rest`() {
        val setId = UUID.randomUUID()
        val exercise = buildTemplateExercise(intraSetRestInSeconds = null)

        val previewItems = buildExerciseTemplatePreviewItems(
            sets = listOf(
                WeightSet(
                    id = setId,
                    reps = 10,
                    weight = 12.0,
                    subCategory = SetSubCategory.WorkSet,
                )
            ),
            exercise = exercise,
            equipment = null,
        )

        assertEquals(
            listOf(
                SetPreviewItemUiModel(
                    setId = setId,
                    rows = listOf(
                        SetTableRowUiModel.Data(
                            identifier = "1",
                            primaryValue = "12.0 kg",
                            secondaryValue = "10",
                        )
                    ),
                )
            ),
            previewItems
        )
    }

    private fun buildTemplateExercise(intraSetRestInSeconds: Int?) = Exercise(
        id = UUID.randomUUID(),
        enabled = true,
        name = "Single Arm Press",
        notes = "",
        sets = emptyList(),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 0.0,
        minReps = 0,
        maxReps = 0,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        intraSetRestInSeconds = intraSetRestInSeconds,
    )

    private fun buildWeightSetHistory(
        id: UUID,
        workoutHistoryId: UUID,
        exerciseId: UUID,
        setId: UUID,
        start: LocalDateTime,
        executionSequence: UInt,
        subCategory: SetSubCategory = SetSubCategory.WorkSet,
    ) = SetHistory(
        id = id,
        workoutHistoryId = workoutHistoryId,
        exerciseId = exerciseId,
        setId = setId,
        order = 0u,
        startTime = start,
        endTime = start.plusSeconds(20),
        setData = WeightSetData(
            actualReps = 10,
            actualWeight = 12.0,
            volume = 120.0,
            subCategory = subCategory,
        ),
        skipped = false,
        executionSequence = executionSequence,
    )

    private fun buildWeightSetHistory(
        exerciseId: UUID,
        setId: UUID,
    ) = buildWeightSetHistory(
        id = UUID.randomUUID(),
        workoutHistoryId = UUID.randomUUID(),
        exerciseId = exerciseId,
        setId = setId,
        start = LocalDateTime.of(2026, 4, 30, 10, 0, 0),
        executionSequence = 0u,
    )

    private fun buildRestHistory(
        workoutHistoryId: UUID,
        exerciseId: UUID,
        start: LocalDateTime,
        executionSequence: UInt,
        plannedRestSeconds: Int = 5,
    ) = RestHistory(
        id = UUID.randomUUID(),
        workoutHistoryId = workoutHistoryId,
        scope = RestHistoryScope.INTRA_EXERCISE,
        executionSequence = executionSequence,
        setData = RestSetData(
            startTimer = plannedRestSeconds,
            endTimer = 0,
            subCategory = SetSubCategory.WorkSet,
        ),
        startTime = start,
        endTime = start.plusSeconds(plannedRestSeconds.toLong()),
        exerciseId = exerciseId,
        restSetId = UUID.randomUUID(),
        order = 0u,
    )
}
