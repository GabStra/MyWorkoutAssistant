package com.gabstra.myworkoutassistant

import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Generic
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import java.util.Calendar
import java.util.UUID
import com.gabstra.myworkoutassistant.mergeWorkoutStore
import com.gabstra.myworkoutassistant.ConflictResolution

sealed class ScreenData() {
    class Workouts(val selectedTabIndex : Int) : ScreenData()
    class Settings() : ScreenData()
    class ErrorLogs() : ScreenData()
    class NewWorkout() : ScreenData()
    class Workout(val workoutId: UUID) : ScreenData()
    class EditWorkout(val workoutId: UUID) : ScreenData()
    class WorkoutDetail(val workoutId: UUID) : ScreenData()
    class WorkoutHistory(val workoutId: UUID,val workoutHistoryId: UUID? = null) : ScreenData()
    class ExerciseDetail(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()
    class ExerciseHistory(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()

    class NewExercise(val workoutId: UUID) : ScreenData()
    class EditExercise(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()

    class NewSuperset(val workoutId: UUID) : ScreenData()
    class EditSuperset(val workoutId: UUID, val selectedSupersetId: UUID) : ScreenData()

    class NewRest(val workoutId: UUID, val parentExerciseId: UUID?) : ScreenData()
    class EditRest(val workoutId: UUID, val selectedRest: Rest) : ScreenData()

    class NewRestSet(val workoutId: UUID, val parentExerciseId: UUID) : ScreenData()
    class EditRestSet(val workoutId: UUID, val selectedRestSet: RestSet, val parentExerciseId: UUID) : ScreenData()

    class NewSet(val workoutId: UUID, val parentExerciseId: UUID) : ScreenData()
    class EditSet(val workoutId: UUID, val selectedSet: Set, val parentExerciseId: UUID) : ScreenData()

    class NewEquipment(val equipmentType: EquipmentType) : ScreenData()
    class EditEquipment(val equipmentId: UUID, val equipmentType: EquipmentType) : ScreenData()
}


class AppViewModel() : ViewModel() {
    private var screenDataStack = mutableListOf<ScreenData>(ScreenData.Workouts(0))

    // Convert currentScreenData to a MutableState
    var currentScreenData: ScreenData by mutableStateOf(screenDataStack.lastOrNull() ?: ScreenData.Workouts(0))
        private set

    private var _userAge = mutableIntStateOf(0)
    val userAge: State<Int> = _userAge

    private val _updateNotificationFlow = MutableStateFlow<String?>(null)
    val updateNotificationFlow = _updateNotificationFlow.asStateFlow()

    var selectedHomeTab by mutableIntStateOf(0)
        private set

    fun triggerUpdate() {
        _updateNotificationFlow.value = System.currentTimeMillis().toString()
    }

    var checkedHealthPermission by mutableStateOf(false)
        private set

    fun setHealthPermissionsChecked() {
        checkedHealthPermission = true
    }

    var hasHealthPermissions by mutableStateOf(false)
        private set

    fun setHealthPermissions(hasPermissions: Boolean) {
        hasHealthPermissions = hasPermissions
    }

    private val _updateMobileFlow = MutableStateFlow<String?>(null)
    val updateMobileFlow = _updateMobileFlow.asStateFlow()

    fun triggerMobile() {
        _updateMobileFlow.value = System.currentTimeMillis().toString()
    }

    private val _showResumeWorkoutDialog = mutableStateOf(false)
    val showResumeWorkoutDialog: State<Boolean> = _showResumeWorkoutDialog

    private val _incompleteWorkouts = mutableStateOf<List<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout>>(emptyList())
    val incompleteWorkouts: State<List<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout>> = _incompleteWorkouts

    fun showResumeWorkoutDialog(incompleteWorkouts: List<com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel.IncompleteWorkout>) {
        _incompleteWorkouts.value = incompleteWorkouts
        _showResumeWorkoutDialog.value = true
    }

    fun hideResumeWorkoutDialog() {
        _showResumeWorkoutDialog.value = false
        _incompleteWorkouts.value = emptyList()
    }

    fun setHomeTab(tabIndex: Int) {
        selectedHomeTab = tabIndex
    }

    fun initScreenData(screenData: ScreenData) {
        screenDataStack.clear()
        currentScreenData = screenData
    }

    fun setScreenData(screenData: ScreenData,skipStack: Boolean = false) {
        // Note: Cannot log here without context - logging moved to composables
        currentScreenData = screenData
        if(!skipStack){
            screenDataStack.add(screenData)
        }
    }

    //function to update current screen data
    fun updateScreenData(screenData: ScreenData) {
        currentScreenData = screenData
        screenDataStack[screenDataStack.size - 1] = screenData
    }

    fun goBack(): Boolean {
        if (screenDataStack.size > 1) {
            screenDataStack.removeAt(screenDataStack.size - 1)
            currentScreenData = screenDataStack.last()
            return true
        } else if (screenDataStack.size == 1) {
            // Handle the case where stack size is 1
            // You can perform some action here if needed
            return false
        }
        return false
    }
    var workoutStore by mutableStateOf(WorkoutStore(
        workouts = emptyList(),
        polarDeviceId = null,
        birthDateYear = 0,
        weightKg = 0.0,
        equipments = emptyList(),
        progressionPercentageAmount = 0.0
    ))
        private set

    private val _workoutsFlow = MutableStateFlow(workoutStore.workouts)
    val workoutsFlow = _workoutsFlow.asStateFlow()

    fun getEquipmentById(equipmentId: UUID): WeightLoadedEquipment? {
        return (equipments + generic).find { it.id == equipmentId }
    }

    fun getWorkoutById(workoutId: UUID): Workout? {
        return workouts.find { it.id == workoutId }
    }

    fun getExerciseById(workout: Workout, exerciseId: UUID): Exercise? {
        return findExerciseInComponents(workout.workoutComponents, exerciseId)
    }

    private fun findExerciseInComponents(components: List<WorkoutComponent>, exerciseId: UUID): Exercise? {
        for (component in components) {
            if (component is Exercise && component.id == exerciseId) {
                return component
            }
            if (component is Superset) {
                val exerciseInSuperset = findExerciseInComponents(component.exercises, exerciseId)
                if (exerciseInSuperset != null) {
                    return exerciseInSuperset
                }
            }
        }
        return null
    }

    var workouts: List<Workout>
        get() = workoutStore.workouts
        private set(value) {
            val adjustedWorkouts = value.map { workout ->
                val adjustedWorkoutComponents = workout.workoutComponents.map { workoutComponent ->
                    when (workoutComponent) {
                        is Exercise -> workoutComponent.copy(sets = ensureRestSeparatedBySets(workoutComponent.sets))
                        is Superset -> workoutComponent.copy(exercises = workoutComponent.exercises.map { exercise ->
                            exercise.copy(sets = ensureRestSeparatedBySets(exercise.sets))
                        })
                        is Rest -> workoutComponent
                    }
                }

                workout.copy(workoutComponents = ensureRestSeparatedByExercises(adjustedWorkoutComponents))
            }

            _workoutsFlow.value = adjustedWorkouts
            workoutStore = workoutStore.copy(workouts = adjustedWorkouts)
            triggerMobile()
        }

    var equipments: List<WeightLoadedEquipment>
        get() = workoutStore.equipments
        private set(value) {
            _equipmentsFlow.value = value
            workoutStore = workoutStore.copy(equipments = value)
            triggerMobile()
        }

    private val _equipmentsFlow = MutableStateFlow(workoutStore.equipments)
    val equipmentsFlow = _equipmentsFlow.asStateFlow()

    public val GENERIC_ID = UUID.fromString("babe5d97-a86d-4ec2-84b6-634034aa847c")
    private val generic = Generic(GENERIC_ID, name = "Generic")

    val equipmentsFlowWithGeneric: StateFlow<List<WeightLoadedEquipment>> = _equipmentsFlow
        .map { equipments ->
            if (equipments.any { it.id == GENERIC_ID }) equipments
            else equipments + generic
        }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = run {
                val base = workoutStore.equipments
                if (base.any { it.id == GENERIC_ID }) base else base + generic
            }
        )

    fun updateWorkoutStore(newWorkoutStore: WorkoutStore,triggerSend:Boolean = true) {
        val adjustedWorkouts = newWorkoutStore.workouts.map { workout ->
            val adjustedWorkoutComponents = workout.workoutComponents.map { workoutComponent ->
                when (workoutComponent) {
                    is Exercise -> workoutComponent.copy(sets = ensureRestSeparatedBySets(workoutComponent.sets))
                    is Superset -> workoutComponent.copy(exercises = workoutComponent.exercises.map { exercise ->
                        exercise.copy(sets = ensureRestSeparatedBySets(exercise.sets))
                    })
                    is Rest -> workoutComponent
                }
            }

            workout.copy(workoutComponents = ensureRestSeparatedByExercises(adjustedWorkoutComponents))
        }

        workoutStore = newWorkoutStore.copy(workouts = adjustedWorkouts)
        val currentYear = Calendar.getInstance().get(Calendar.YEAR)
        _userAge.intValue =  currentYear - workoutStore.birthDateYear
        _workoutsFlow.value = newWorkoutStore.workouts
        _equipmentsFlow.value = newWorkoutStore.equipments
        if(triggerSend) triggerMobile()
    }

    fun updateEquipments(newEquipments: List<WeightLoadedEquipment>) {
        equipments = newEquipments
    }

    fun updateWorkouts(newWorkouts: List<Workout>) {
        workouts = newWorkouts
    }

    private fun applyWorkoutUpdate(
        currentWorkouts: List<Workout>,
        oldWorkout: Workout,
        updatedWorkout: Workout,
        hasHistory: Boolean
    ): List<Workout> {
        return if (hasHistory) {
            WorkoutManager.updateWorkout(currentWorkouts, oldWorkout, updatedWorkout)
        } else {
            WorkoutManager.updateWorkoutOld(currentWorkouts, oldWorkout, updatedWorkout)
        }
    }

    fun updateWorkoutVersioned(oldWorkout: Workout, updatedWorkout: Workout, hasHistory: Boolean) {
        workouts = applyWorkoutUpdate(workouts, oldWorkout, updatedWorkout, hasHistory)
    }

    fun updateWorkoutComponentVersioned(
        parentWorkout: Workout,
        oldWorkoutComponent: WorkoutComponent,
        updatedWorkoutComponent: WorkoutComponent,
        hasHistory: Boolean
    ) {
        val updatedComponents = WorkoutManager.updateWorkoutComponentsRecursively(
            parentWorkout.workoutComponents,
            oldWorkoutComponent,
            updatedWorkoutComponent
        )
        val updatedWorkout = parentWorkout.copy(workoutComponents = updatedComponents)
        updateWorkoutVersioned(parentWorkout, updatedWorkout, hasHistory)
    }

    fun addWorkoutComponentVersioned(
        workout: Workout,
        newWorkoutComponent: WorkoutComponent,
        hasHistory: Boolean
    ) {
        val updatedWorkout = workout.copy(workoutComponents = workout.workoutComponents + newWorkoutComponent)
        updateWorkoutVersioned(workout, updatedWorkout, hasHistory)
    }

    fun addSetToExerciseVersioned(
        workout: Workout,
        exercise: Exercise,
        newSet: Set,
        hasHistory: Boolean
    ) {
        val updatedComponents = WorkoutManager.addSetToExerciseRecursively(
            workout.workoutComponents,
            exercise,
            newSet
        )
        val updatedWorkout = workout.copy(workoutComponents = updatedComponents)
        updateWorkoutVersioned(workout, updatedWorkout, hasHistory)
    }

    fun updateSetInExerciseVersioned(
        workout: Workout,
        exercise: Exercise,
        oldSet: Set,
        updatedSet: Set,
        hasHistory: Boolean
    ) {
        val updatedComponents = WorkoutManager.updateSetInExerciseRecursively(
            workout.workoutComponents,
            exercise,
            oldSet,
            updatedSet
        )
        val updatedWorkout = workout.copy(workoutComponents = updatedComponents)
        updateWorkoutVersioned(workout, updatedWorkout, hasHistory)
    }

    fun moveComponentsVersioned(
        sourceWorkout: Workout,
        componentsToMove: List<WorkoutComponent>,
        targetWorkout: Workout,
        sourceHasHistory: Boolean,
        targetHasHistory: Boolean
    ) {
        val updatedWorkouts = WorkoutManager.moveWorkoutComponents(
            workouts,
            sourceWorkout,
            componentsToMove,
            targetWorkout
        )
        val updatedSourceWorkout = updatedWorkouts.firstOrNull { it.id == sourceWorkout.id } ?: return
        // Find target workout by globalId and isActive to handle versioned workouts correctly
        val updatedTargetWorkout = updatedWorkouts.firstOrNull { it.globalId == targetWorkout.globalId && it.isActive } ?: return

        var nextWorkouts = workouts
        nextWorkouts = applyWorkoutUpdate(nextWorkouts, sourceWorkout, updatedSourceWorkout, sourceHasHistory)
        nextWorkouts = applyWorkoutUpdate(nextWorkouts, targetWorkout, updatedTargetWorkout, targetHasHistory)
        workouts = nextWorkouts
    }

    fun addNewWorkout(newWorkout: Workout) {
        workouts = workouts + newWorkout.copy(order = workouts.size)
    }

    /**
     * Imports a WorkoutStore and merges it with the existing one.
     * 
     * @param importedWorkoutStore The WorkoutStore to import
     * @param conflictResolution How to handle ID conflicts (default: GENERATE_NEW_IDS)
     */
    fun importWorkoutStore(
        importedWorkoutStore: WorkoutStore,
        conflictResolution: ConflictResolution = ConflictResolution.GENERATE_NEW_IDS
    ) {
        val merged = mergeWorkoutStore(workoutStore, importedWorkoutStore, conflictResolution)
        updateWorkoutStore(merged)
    }
}

