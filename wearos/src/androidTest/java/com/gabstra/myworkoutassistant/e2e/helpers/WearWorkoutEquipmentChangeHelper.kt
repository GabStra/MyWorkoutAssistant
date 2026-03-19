package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.lifecycle.ViewModelProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.workout.recovery.WorkoutRecoverySnapshotCodec
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking

object WearWorkoutEquipmentChangeHelper {
    data class CurrentSetSnapshot(
        val exerciseName: String,
        val equipmentName: String?,
        val additionalWeight: Double?
    )

    data class ExerciseEquipmentSnapshot(
        val exerciseName: String,
        val equipmentName: String?,
        val isRefreshing: Boolean
    )

    fun waitForCurrentSetSnapshot(
        timeoutMs: Long,
        predicate: (CurrentSetSnapshot) -> Boolean
    ): CurrentSetSnapshot? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val snapshot = readCurrentSetSnapshot()
            if (snapshot != null && predicate(snapshot)) {
                return snapshot
            }
            Thread.sleep(150)
        }
        return null
    }

    fun waitForPersistedExerciseEquipment(
        context: Context,
        workoutName: String,
        exerciseName: String,
        expectedEquipmentName: String?,
        timeoutMs: Long
    ): Boolean = runBlocking {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (
                readPersistedExerciseEquipmentName(
                    context = context,
                    workoutName = workoutName,
                    exerciseName = exerciseName
                ) == expectedEquipmentName
            ) {
                return@runBlocking true
            }
            delay(150)
        }
        false
    }

    fun waitForLiveExerciseEquipment(
        exerciseName: String,
        expectedEquipmentName: String?,
        timeoutMs: Long
    ): CurrentSetSnapshot? {
        return waitForCurrentSetSnapshot(timeoutMs) { snapshot ->
            snapshot.exerciseName == exerciseName &&
                snapshot.equipmentName == expectedEquipmentName
        }
    }

    fun waitForObservedExerciseEquipment(
        context: Context,
        exerciseName: String,
        expectedEquipmentName: String?,
        timeoutMs: Long
    ): CurrentSetSnapshot? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val liveSnapshot = readCurrentSetSnapshot()
            if (
                liveSnapshot?.exerciseName == exerciseName &&
                liveSnapshot.equipmentName == expectedEquipmentName
            ) {
                return liveSnapshot
            }

            val definitionSnapshot = readForegroundExerciseEquipmentSnapshot(exerciseName)
            if (
                definitionSnapshot != null &&
                !definitionSnapshot.isRefreshing &&
                definitionSnapshot.equipmentName == expectedEquipmentName
            ) {
                return CurrentSetSnapshot(
                    exerciseName = definitionSnapshot.exerciseName,
                    equipmentName = definitionSnapshot.equipmentName,
                    additionalWeight = liveSnapshot?.additionalWeight
                )
            }

            val runtimeSnapshot = readRuntimeSnapshotCurrentSet(context)
            if (
                runtimeSnapshot?.exerciseName == exerciseName &&
                runtimeSnapshot.equipmentName == expectedEquipmentName
            ) {
                return runtimeSnapshot
            }

            Thread.sleep(150)
        }
        return null
    }

    fun waitForRuntimeSnapshotExerciseEquipment(
        context: Context,
        exerciseName: String,
        expectedEquipmentName: String?,
        timeoutMs: Long
    ): Boolean = runBlocking {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val snapshot = readRuntimeSnapshotCurrentSet(context)
            if (snapshot?.exerciseName == exerciseName && snapshot.equipmentName == expectedEquipmentName) {
                return@runBlocking true
            }
            delay(150)
        }
        false
    }

    fun readCurrentSetSnapshot(): CurrentSetSnapshot? {
        var snapshot: CurrentSetSnapshot? = null
        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            val exercise = viewModel.exercisesById[currentState.exerciseId] ?: return@withResumedViewModel
            val equipmentName = currentState.equipmentId
                ?.let(viewModel::getEquipmentById)
                ?.name
            val additionalWeight = (currentState.currentSetData as? BodyWeightSetData)?.additionalWeight
            snapshot = CurrentSetSnapshot(
                exerciseName = exercise.name,
                equipmentName = equipmentName,
                additionalWeight = additionalWeight
            )
        }
        return snapshot
    }

    private fun readForegroundExerciseEquipmentSnapshot(exerciseName: String): ExerciseEquipmentSnapshot? {
        var snapshot: ExerciseEquipmentSnapshot? = null
        withResumedViewModel { viewModel ->
            val exercise = viewModel.exercisesById.values.firstOrNull { it.name == exerciseName }
                ?: return@withResumedViewModel
            val equipmentName = exercise.equipmentId
                ?.let(viewModel::getEquipmentById)
                ?.name
            snapshot = ExerciseEquipmentSnapshot(
                exerciseName = exercise.name,
                equipmentName = equipmentName,
                isRefreshing = viewModel.isRefreshing.value
            )
        }
        return snapshot
    }

    private fun readPersistedExerciseEquipmentName(
        context: Context,
        workoutName: String,
        exerciseName: String
    ): String? {
        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName } ?: return null
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull { it.name == exerciseName }
            ?: return null

        return exercise.equipmentId
            ?.let { equipmentId -> workoutStore.equipments.firstOrNull { it.id == equipmentId } }
            ?.name
    }

    private fun readRuntimeSnapshotCurrentSet(context: Context): CurrentSetSnapshot? {
        val snapshotJson = context
            .getSharedPreferences("workout_recovery_checkpoint", Context.MODE_PRIVATE)
            .getString("runtimeSnapshotJson", null)
            ?: return null
        val decoded = WorkoutRecoverySnapshotCodec.decode(snapshotJson) ?: return null
        val currentState = flattenSequence(decoded.sequenceItems)
            .getOrNull(decoded.currentIndex) as? WorkoutState.Set
            ?: return null
        val workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
        val exercise = workoutStore.workouts
            .asSequence()
            .flatMap { workout -> workout.workoutComponents.asSequence() }
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull { it.id == currentState.exerciseId }
            ?: return null
        val equipmentName = currentState.equipmentId
            ?.let { equipmentId -> workoutStore.equipments.firstOrNull { it.id == equipmentId } }
            ?.name
        val additionalWeight = (currentState.currentSetData as? BodyWeightSetData)?.additionalWeight
        return CurrentSetSnapshot(
            exerciseName = exercise.name,
            equipmentName = equipmentName,
            additionalWeight = additionalWeight
        )
    }

    private fun flattenSequence(sequenceItems: List<WorkoutStateSequenceItem>): List<WorkoutState> =
        sequenceItems.flatMap { item ->
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
        }

    private fun withResumedViewModel(block: (AppViewModel) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: return@runOnMainSync
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            block(viewModel)
        }
    }
}
