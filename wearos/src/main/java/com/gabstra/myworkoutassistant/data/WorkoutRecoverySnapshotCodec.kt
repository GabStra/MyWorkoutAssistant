package com.gabstra.myworkoutassistant.data

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.typeconverters.SetDataTypeConverter
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.UUID

internal data class WorkoutRecoveryRuntimeSnapshot(
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val currentIndex: Int,
    val sequenceItems: List<SequenceItemDto>,
    val updatedAtEpochMs: Long
)

internal data class DecodedRecoveryRuntimeSnapshot(
    val workoutId: UUID,
    val workoutHistoryId: UUID?,
    val currentIndex: Int,
    val sequenceItems: List<WorkoutStateSequenceItem>
)

internal data class SequenceItemDto(
    val type: String,
    val container: ContainerDto? = null,
    val rest: StateDto? = null
)

internal data class ContainerDto(
    val type: String,
    val exerciseId: String? = null,
    val supersetId: String? = null,
    val childItems: List<ExerciseChildItemDto>? = null,
    val childStates: List<StateDto>? = null
)

internal data class ExerciseChildItemDto(
    val type: String,
    val states: List<StateDto>
)

internal data class StateDto(
    val type: String,
    val exerciseId: String? = null,
    val setJson: String? = null,
    val calibrationSetJson: String? = null,
    val setIndex: Int? = null,
    val order: Int? = null,
    val previousSetDataJson: String? = null,
    val currentSetDataJson: String,
    val startTimeEpochMs: Long? = null,
    val skipped: Boolean? = null,
    val hasNoHistory: Boolean? = null,
    val lowerBoundMaxHRPercent: Float? = null,
    val upperBoundMaxHRPercent: Float? = null,
    val currentBodyWeight: Double? = null,
    val streak: Int? = null,
    val progressionState: String? = null,
    val isWarmupSet: Boolean? = null,
    val isUnilateral: Boolean? = null,
    val intraSetTotal: Int? = null,
    val intraSetCounter: Int? = null,
    val isCalibrationSet: Boolean? = null,
    val isCalibrationManagedWorkSet: Boolean? = null,
    val isIntraSetRest: Boolean? = null,
    val isLoadConfirmed: Boolean? = null
)

internal object WorkoutRecoverySnapshotCodec {
    private val gson: Gson = Gson()
    private val setGson: Gson = GsonBuilder()
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .registerTypeAdapter(RestSet::class.java, SetAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .create()
    private val setDataConverter = SetDataTypeConverter()

    fun encode(
        workoutId: UUID,
        workoutHistoryId: UUID?,
        currentIndex: Int,
        sequenceItems: List<WorkoutStateSequenceItem>
    ): String {
        val snapshot = WorkoutRecoveryRuntimeSnapshot(
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            currentIndex = currentIndex,
            sequenceItems = sequenceItems.map { it.toDto() },
            updatedAtEpochMs = System.currentTimeMillis()
        )
        return gson.toJson(snapshot)
    }

    fun decode(json: String): DecodedRecoveryRuntimeSnapshot? {
        val snapshot = runCatching {
            gson.fromJson(json, WorkoutRecoveryRuntimeSnapshot::class.java)
        }.getOrNull() ?: return null

        val decodedSequence = snapshot.sequenceItems.mapNotNull { it.toDomain() }
        if (decodedSequence.size != snapshot.sequenceItems.size || decodedSequence.isEmpty()) return null
        val boundedIndex = snapshot.currentIndex.coerceIn(0, decodedSequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> container.childItems.flatMap { child ->
                            when (child) {
                                is ExerciseChildItem.Normal -> listOf(child.state)
                                is ExerciseChildItem.CalibrationExecutionBlock -> child.childStates
                                is ExerciseChildItem.LoadSelectionBlock -> child.childStates
                                is ExerciseChildItem.UnilateralSetBlock -> child.childStates
                            }
                        }
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
            }
        }.lastIndex)

        return DecodedRecoveryRuntimeSnapshot(
            workoutId = snapshot.workoutId,
            workoutHistoryId = snapshot.workoutHistoryId,
            currentIndex = boundedIndex,
            sequenceItems = decodedSequence
        )
    }

    private fun WorkoutStateSequenceItem.toDto(): SequenceItemDto = when (this) {
        is WorkoutStateSequenceItem.Container -> SequenceItemDto(
            type = "CONTAINER",
            container = container.toDto()
        )
        is WorkoutStateSequenceItem.RestBetweenExercises -> SequenceItemDto(
            type = "REST_BETWEEN_EXERCISES",
            rest = rest.toDto()
        )
    }

    private fun WorkoutStateContainer.toDto(): ContainerDto = when (this) {
        is WorkoutStateContainer.ExerciseState -> ContainerDto(
            type = "EXERCISE",
            exerciseId = exerciseId.toString(),
            childItems = childItems.map { child ->
                when (child) {
                    is ExerciseChildItem.Normal -> ExerciseChildItemDto("NORMAL", listOf(child.state.toDto()))
                    is ExerciseChildItem.CalibrationExecutionBlock ->
                        ExerciseChildItemDto("CALIBRATION_EXECUTION_BLOCK", child.childStates.map { it.toDto() })
                    is ExerciseChildItem.LoadSelectionBlock ->
                        ExerciseChildItemDto("LOAD_SELECTION_BLOCK", child.childStates.map { it.toDto() })
                    is ExerciseChildItem.UnilateralSetBlock ->
                        ExerciseChildItemDto("UNILATERAL_SET_BLOCK", child.childStates.map { it.toDto() })
                }
            }
        )
        is WorkoutStateContainer.SupersetState -> ContainerDto(
            type = "SUPERSET",
            supersetId = supersetId.toString(),
            childStates = childStates.map { it.toDto() }
        )
    }

    private fun WorkoutState.toDto(): StateDto = when (this) {
        is WorkoutState.Set -> StateDto(
            type = "SET",
            exerciseId = exerciseId.toString(),
            setJson = setGson.toJson(set),
            setIndex = setIndex.toInt(),
            previousSetDataJson = previousSetData?.let { setDataConverter.fromSetData(copySetData(it)) },
            currentSetDataJson = setDataConverter.fromSetData(copySetData(currentSetData)),
            startTimeEpochMs = startTime?.toEpochMillis(),
            skipped = skipped,
            hasNoHistory = hasNoHistory,
            lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = upperBoundMaxHRPercent,
            currentBodyWeight = currentBodyWeight,
            streak = streak,
            progressionState = progressionState?.name,
            isWarmupSet = isWarmupSet,
            isUnilateral = isUnilateral,
            intraSetTotal = intraSetTotal?.toInt(),
            intraSetCounter = intraSetCounter.toInt(),
            isCalibrationSet = isCalibrationSet,
            isCalibrationManagedWorkSet = isCalibrationManagedWorkSet
        )
        is WorkoutState.CalibrationLoadSelection -> StateDto(
            type = "CALIBRATION_LOAD",
            exerciseId = exerciseId.toString(),
            calibrationSetJson = setGson.toJson(calibrationSet),
            setIndex = setIndex.toInt(),
            previousSetDataJson = previousSetData?.let { setDataConverter.fromSetData(copySetData(it)) },
            currentSetDataJson = setDataConverter.fromSetData(copySetData(currentSetData)),
            lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = upperBoundMaxHRPercent,
            currentBodyWeight = currentBodyWeight,
            isUnilateral = isUnilateral,
            isLoadConfirmed = isLoadConfirmed
        )
        is WorkoutState.CalibrationRIRSelection -> StateDto(
            type = "CALIBRATION_RIR",
            exerciseId = exerciseId.toString(),
            calibrationSetJson = setGson.toJson(calibrationSet),
            setIndex = setIndex.toInt(),
            currentSetDataJson = setDataConverter.fromSetData(copySetData(currentSetData)),
            lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
            upperBoundMaxHRPercent = upperBoundMaxHRPercent,
            currentBodyWeight = currentBodyWeight
        )
        is WorkoutState.Rest -> StateDto(
            type = "REST",
            exerciseId = exerciseId?.toString(),
            setJson = setGson.toJson(set),
            order = order.toInt(),
            currentSetDataJson = setDataConverter.fromSetData(copySetData(currentSetData)),
            startTimeEpochMs = startTime?.toEpochMillis(),
            isIntraSetRest = isIntraSetRest
        )
        is WorkoutState.Preparing -> error("Preparing should not be serialized in runtime snapshot")
        is WorkoutState.Completed -> error("Completed should not be serialized in runtime snapshot")
    }

    private fun SequenceItemDto.toDomain(): WorkoutStateSequenceItem? {
        return when (type) {
            "CONTAINER" -> container?.toDomain()?.let { WorkoutStateSequenceItem.Container(it) }
            "REST_BETWEEN_EXERCISES" -> {
                val restState = rest?.toDomain() as? WorkoutState.Rest ?: return null
                WorkoutStateSequenceItem.RestBetweenExercises(restState)
            }
            else -> null
        }
    }

    private fun ContainerDto.toDomain(): WorkoutStateContainer? {
        return when (type) {
            "EXERCISE" -> {
                val id = exerciseId?.toUuidOrNull() ?: return null
                val mappedItems = childItems?.mapNotNull { child ->
                    val states = child.states.mapNotNull { it.toDomain() }.toMutableList()
                    if (states.size != child.states.size || states.isEmpty()) return@mapNotNull null
                    when (child.type) {
                        "NORMAL" -> ExerciseChildItem.Normal(states.first())
                        "CALIBRATION_EXECUTION_BLOCK" -> ExerciseChildItem.CalibrationExecutionBlock(states)
                        "LOAD_SELECTION_BLOCK" -> ExerciseChildItem.LoadSelectionBlock(states)
                        "UNILATERAL_SET_BLOCK" -> ExerciseChildItem.UnilateralSetBlock(states)
                        else -> null
                    }
                }?.toMutableList() ?: return null
                WorkoutStateContainer.ExerciseState(id, mappedItems)
            }
            "SUPERSET" -> {
                val id = supersetId?.toUuidOrNull() ?: return null
                val mappedStates = childStates?.mapNotNull { it.toDomain() }?.toMutableList() ?: return null
                if (mappedStates.size != childStates.size || mappedStates.isEmpty()) return null
                WorkoutStateContainer.SupersetState(id, mappedStates)
            }
            else -> null
        }
    }

    private fun StateDto.toDomain(): WorkoutState? {
        return when (type) {
            "SET" -> {
                val parsedSet = setJson?.toSetOrNull() ?: return null
                val currentData = currentSetDataJson.toSetDataOrNull() ?: initializeSetData(parsedSet)
                val previousData = previousSetDataJson?.toSetDataOrNull()
                WorkoutState.Set(
                    exerciseId = exerciseId?.toUuidOrNull() ?: return null,
                    set = parsedSet,
                    setIndex = (setIndex ?: return null).toUInt(),
                    previousSetData = previousData,
                    currentSetDataState = mutableStateOf(copySetData(currentData)),
                    hasNoHistory = hasNoHistory ?: false,
                    startTime = startTimeEpochMs?.toLocalDateTime(),
                    skipped = skipped ?: false,
                    lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent = upperBoundMaxHRPercent,
                    currentBodyWeight = currentBodyWeight ?: 0.0,
                    plateChangeResult = null,
                    streak = streak ?: 0,
                    progressionState = progressionState?.let { runCatching { ProgressionState.valueOf(it) }.getOrNull() },
                    isWarmupSet = isWarmupSet ?: false,
                    equipment = null,
                    isUnilateral = isUnilateral ?: false,
                    intraSetTotal = intraSetTotal?.toUInt(),
                    intraSetCounter = (intraSetCounter ?: 0).toUInt(),
                    isCalibrationSet = isCalibrationSet ?: false,
                    isCalibrationManagedWorkSet = isCalibrationManagedWorkSet ?: false
                )
            }

            "CALIBRATION_LOAD" -> {
                val parsedSet = calibrationSetJson?.toSetOrNull() ?: return null
                val currentData = currentSetDataJson.toSetDataOrNull() ?: initializeSetData(parsedSet)
                val previousData = previousSetDataJson?.toSetDataOrNull()
                WorkoutState.CalibrationLoadSelection(
                    exerciseId = exerciseId?.toUuidOrNull() ?: return null,
                    calibrationSet = parsedSet,
                    setIndex = (setIndex ?: return null).toUInt(),
                    previousSetData = previousData,
                    currentSetDataState = mutableStateOf(copySetData(currentData)),
                    equipment = null,
                    lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent = upperBoundMaxHRPercent,
                    currentBodyWeight = currentBodyWeight ?: 0.0,
                    isUnilateral = isUnilateral ?: false,
                    isLoadConfirmed = isLoadConfirmed ?: false
                )
            }

            "CALIBRATION_RIR" -> {
                val parsedSet = calibrationSetJson?.toSetOrNull() ?: return null
                val currentData = currentSetDataJson.toSetDataOrNull() ?: initializeSetData(parsedSet)
                WorkoutState.CalibrationRIRSelection(
                    exerciseId = exerciseId?.toUuidOrNull() ?: return null,
                    calibrationSet = parsedSet,
                    setIndex = (setIndex ?: return null).toUInt(),
                    currentSetDataState = mutableStateOf(copySetData(currentData)),
                    equipment = null,
                    lowerBoundMaxHRPercent = lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent = upperBoundMaxHRPercent,
                    currentBodyWeight = currentBodyWeight ?: 0.0
                )
            }

            "REST" -> {
                val parsedSet = setJson?.toSetOrNull() ?: return null
                val currentData = currentSetDataJson.toSetDataOrNull() ?: initializeSetData(parsedSet)
                WorkoutState.Rest(
                    set = parsedSet,
                    order = (order ?: return null).toUInt(),
                    currentSetDataState = mutableStateOf(copySetData(currentData)),
                    exerciseId = exerciseId?.toUuidOrNull(),
                    startTime = startTimeEpochMs?.toLocalDateTime(),
                    isIntraSetRest = isIntraSetRest ?: false
                )
            }
            else -> null
        }
    }

    private fun String.toSetOrNull(): Set? = runCatching { setGson.fromJson(this, Set::class.java) }.getOrNull()
    private fun String.toSetDataOrNull(): SetData? = runCatching { setDataConverter.toSetData(this) }.getOrNull()
    private fun String.toUuidOrNull(): UUID? = runCatching { UUID.fromString(this) }.getOrNull()

    private fun LocalDateTime.toEpochMillis(): Long =
        atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()

    private fun Long.toLocalDateTime(): LocalDateTime =
        LocalDateTime.ofInstant(Instant.ofEpochMilli(this), ZoneId.systemDefault())
}
