package com.gabstra.myworkoutassistant.shared.workout.history.importing

import android.content.Context
import androidx.room.withTransaction
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDateTime
import java.time.LocalTime

/** Validates and appends user-reported history without replacing other profile data. */
object WorkoutHistoryImportService {
    fun validate(
        workoutStore: WorkoutStore,
        targetProfileId: String,
        payload: WorkoutHistoryImportPackage,
    ) {
        require(targetProfileId.isNotBlank()) { "A target profile is required." }
        require(payload.profileId == targetProfileId) { "History package belongs to a different profile." }
        require(payload.format == WorkoutHistoryImportPackage.FORMAT) { "Unsupported history package format." }
        require(payload.formatVersion == WorkoutHistoryImportPackage.FORMAT_VERSION) { "Unsupported history package version." }
        require(payload.workoutHistories.isNotEmpty()) { "History package contains no sessions." }
        require(payload.workoutHistories.map { it.id }.distinct().size == payload.workoutHistories.size) {
            "History package contains duplicate session IDs."
        }
        require(payload.setHistories.map { it.id }.distinct().size == payload.setHistories.size) {
            "History package contains duplicate set-history IDs."
        }

        val workoutsById = workoutStore.workouts.associateBy { it.id }
        val historiesById = payload.workoutHistories.associateBy { it.id }
        val setsByHistory = payload.setHistories.groupBy { it.workoutHistoryId }
        require(setsByHistory.keys.all { id -> id != null && historiesById.containsKey(id) }) {
            "Every imported set must belong to a session in this package."
        }
        require(payload.workoutHistories.all { it.origin == WorkoutHistoryOrigin.USER_IMPORTED }) {
            "Imported sessions must be explicitly marked USER_IMPORTED."
        }

        payload.workoutHistories.forEach { history ->
            val workout = workoutsById[history.workoutId]
                ?: error("Workout ${history.workoutId} is not present in the target workout store.")
            validateHistory(history, workout)
            val historySets = setsByHistory[history.id].orEmpty()
            require(historySets.isNotEmpty()) { "Imported session ${history.id} has no actual working sets." }
            validateSets(history, workout, historySets, workoutStore)
        }
        require(payload.setHistories.all { row -> row.workoutHistoryId?.let(historiesById::containsKey) == true }) {
            "An imported set refers to a session outside this package."
        }
    }

    suspend fun append(
        database: AppDatabase,
        workoutStore: WorkoutStore,
        targetProfileId: String,
        payload: WorkoutHistoryImportPackage,
    ): ImportResult {
        validate(workoutStore, targetProfileId, payload)
        return database.withTransaction {
            val historyDao = database.workoutHistoryDao()
            val setDao = database.setHistoryDao()
            var insertedHistories = 0
            var insertedSets = 0

            payload.workoutHistories.forEach { incoming ->
                val existing = historyDao.getWorkoutHistoryById(incoming.id)
                if (existing == null) {
                    historyDao.insert(incoming)
                    insertedHistories++
                } else {
                    require(existing == incoming) { "Session ID ${incoming.id} already exists with different data." }
                }
            }
            payload.setHistories.forEach { incoming ->
                val existing = setDao.getSetHistoryById(incoming.id)
                if (existing == null) {
                    setDao.insert(incoming)
                    insertedSets++
                } else {
                    require(existing == incoming) { "Set-history ID ${incoming.id} already exists with different data." }
                }
            }
            ImportResult(insertedHistories, insertedSets)
        }
    }

    /** Opens only the payload's named profile database; it does not change the selected profile. */
    suspend fun append(
        context: Context,
        workoutStore: WorkoutStore,
        targetProfileId: String,
        payload: WorkoutHistoryImportPackage,
    ): ImportResult {
        require(payload.profileId == targetProfileId) { "History package belongs to a different profile." }
        require(Profiles.profiles(context).any { it.id == targetProfileId }) {
            "Target profile does not exist on this device."
        }
        return append(AppDatabase.getDatabase(context, targetProfileId), workoutStore, targetProfileId, payload)
    }

    private fun validateHistory(history: WorkoutHistory, workout: Workout) {
        require(history.globalId == workout.globalId) { "History global ID does not match its workout." }
        require(history.recurringSessionId == workout.recurringSessionId) {
            "History recurring-session ID does not match its workout."
        }
        require(history.isDone && history.endReason == WorkoutSessionEndReason.COMPLETED) {
            "Only completed sessions can be imported."
        }
        require(!history.hasBeenSentToHealth) { "Imported sessions must not claim prior Health Connect export." }
        require(history.heartBeatRecords.isEmpty() && history.ibiRecords.isEmpty()) {
            "User-reported history cannot contain device heart-rate records."
        }
        require(history.heartRateSource == null && history.heartRateStreams.isEmpty() &&
            history.heartRateStreamTimes.isEmpty() && history.heartRateStreamsStartEpochMs == null) {
            "User-reported history cannot contain heart-rate stream metadata."
        }
        require(history.restRmssdMs == null && history.restSdnnMs == null && history.sweatLossMl == null &&
            history.skinTempStartC == null && history.skinTempMaxC == null && history.runningResults.isEmpty()) {
            "User-reported history cannot contain unobserved sensor or running measurements."
        }
        require(history.duration >= 0) { "Stored duration cannot be negative." }
        require(history.durationKnown || history.duration == 0) {
            "Unknown duration must use the neutral zero storage value."
        }
        require(!history.durationKnown || history.duration > 0) { "A known session duration must be positive." }
        require(history.startTimeKnown || history.startTime == LocalDateTime.of(history.date, LocalTime.MIDNIGHT)) {
            "Unknown start time must use the date-only neutral storage value."
        }
        require(history.startTimeKnown || history.time == LocalTime.MIDNIGHT) {
            "Unknown start time must use the neutral midnight storage value."
        }
        require(!history.startTimeKnown ||
            (history.startTime.toLocalDate() == history.date && history.startTime.toLocalTime() == history.time)) {
            "Known start date/time fields must agree."
        }
    }

    private fun validateSets(
        history: WorkoutHistory,
        workout: Workout,
        rows: List<SetHistory>,
        store: WorkoutStore,
    ) {
        val exercises = workout.workoutComponents.flatMap { component ->
            when (component) {
                is Exercise -> listOf(component)
                is Superset -> component.exercises
                else -> emptyList()
            }
        }.associateBy { it.id }

        rows.forEach { row ->
            require(row.workoutHistoryId == history.id) { "Set row points to a different workout history." }
            require(!row.skipped) { "Imported rows must represent performed working sets." }
            require(row.startTime == null && row.endTime == null) { "User-reported sets cannot claim set timestamps." }
            require(row.executionSequence == null && row.supersetRound == null && row.supersetExerciseIndex == null) {
                "User-reported sets cannot claim an observed execution sequence or round."
            }
            val exerciseId = requireNotNull(row.exerciseId) { "Imported set has no exercise occurrence ID." }
            val exercise = exercises[exerciseId] ?: error("Exercise $exerciseId is not in the referenced workout.")
            require(row.recurringExerciseId == exercise.recurringExerciseId) {
                "Set recurring track does not match its prescribed exercise slot."
            }
            require(row.exerciseDefinitionIdSnapshot == exercise.exerciseDefinitionId) {
                "Set definition snapshot does not match its exercise occurrence."
            }
            require(row.exerciseTypeSnapshot == exercise.exerciseType.name) {
                "Set exercise-type snapshot does not match its exercise occurrence."
            }
            require(row.equipmentIdSnapshot == exercise.equipmentId ||
                !row.exerciseNameSnapshot.isNullOrBlank()) {
                "A performed equipment substitution must have an explicit performed exercise name."
            }
            require(row.exerciseNameSnapshot == null || row.exerciseNameSnapshot.isNotBlank()) {
                "Performed exercise name cannot be blank."
            }
            row.equipmentIdSnapshot?.let { id ->
                val equipment = store.equipments.firstOrNull { it.id == id }
                    ?: store.accessoryEquipments.firstOrNull { it.id == id }
                    ?: error("Set equipment snapshot $id is not known to this workout store.")
                require(row.equipmentNameSnapshot == equipment.name && row.equipmentTypeSnapshot == equipment.type.name) {
                    "Set equipment name/type snapshots do not match the actual equipment ID."
                }
            }
            val set = exercise.sets.firstOrNull { it.id == row.setId }
                ?: error("Set ${row.setId} is not in exercise $exerciseId.")
            require(set.subCategoryForImport() == SetSubCategory.WorkSet) {
                "Only actual working sets can be imported."
            }
            when {
                set is WeightSet && exercise.exerciseType == ExerciseType.WEIGHT -> {
                    val data = row.setData as? WeightSetData
                        ?: error("Weighted exercise history requires a weight measurement.")
                    validateActual(data.actualReps, data.actualWeight, data.subCategory, data.calibrationRIR, data.autoRegulationRIR)
                }
                set is BodyWeightSet && exercise.exerciseType == ExerciseType.BODY_WEIGHT -> {
                    val data = row.setData as? BodyWeightSetData
                        ?: error("Bodyweight exercise history requires bodyweight set data.")
                    validateActual(data.actualReps, data.additionalWeight, data.subCategory, data.calibrationRIR, data.autoRegulationRIR)
                    require(data.relativeBodyWeightInKg.isFinite() && data.relativeBodyWeightInKg >= 0.0) {
                        "Bodyweight measurement must be finite and nonnegative."
                    }
                    require(data.bodyWeightPercentageSnapshot == exercise.bodyWeightPercentage ||
                        !row.exerciseNameSnapshot.isNullOrBlank()) {
                        "A changed bodyweight load scope needs an explicit performed exercise name."
                    }
                }
                else -> error("Imported history only supports measured weight and bodyweight working sets.")
            }
        }
    }

    private fun validateActual(
        reps: Int,
        load: Double,
        subCategory: SetSubCategory,
        calibrationRir: Double?,
        autoRegulationRir: Double?,
    ) {
        require(reps > 0 && load.isFinite() && load >= 0.0) { "Actual repetitions and load must be valid." }
        require(subCategory == SetSubCategory.WorkSet) { "Warmup and non-work sets are not importable as performed sets." }
        require(calibrationRir == null && autoRegulationRir == null) {
            "Unobserved RIR values cannot be fabricated for user-reported sets."
        }
    }

    private fun com.gabstra.myworkoutassistant.shared.sets.Set.subCategoryForImport(): SetSubCategory? = when (this) {
        is WeightSet -> subCategory
        is BodyWeightSet -> subCategory
        else -> null
    }
}

data class ImportResult(val insertedHistories: Int, val insertedSets: Int)
