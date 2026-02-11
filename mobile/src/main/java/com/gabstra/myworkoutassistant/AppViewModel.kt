package com.gabstra.myworkoutassistant

import android.app.Application
import android.content.Context
import android.util.Log
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.migrateWorkoutStoreSetIdsIfNeeded
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Generic
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.util.Calendar
import java.util.UUID

sealed class ScreenData() {
    class Workouts(val selectedTabIndex : Int) : ScreenData()
    class Settings() : ScreenData()
    class ErrorLogs() : ScreenData()
    class NewWorkout(val workoutPlanId: UUID? = null) : ScreenData()
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
    class InsertRestSetAfter(val workoutId: UUID, val exerciseId: UUID, val afterSetId: UUID) : ScreenData()
    class InsertRestAfter(val workoutId: UUID, val afterComponentId: UUID) : ScreenData()

    class NewSet(val workoutId: UUID, val parentExerciseId: UUID) : ScreenData()
    class EditSet(val workoutId: UUID, val selectedSet: Set, val parentExerciseId: UUID) : ScreenData()

    class NewEquipment(val equipmentType: EquipmentType) : ScreenData()
    class EditEquipment(val equipmentId: UUID, val equipmentType: EquipmentType) : ScreenData()
    
    /**
     * Converts ScreenData to a Bundle-compatible String key for use with SaveableStateProvider.
     * This is necessary because ScreenData instances cannot be directly used as Bundle keys on Android.
     */
    fun toSaveableKey(): String {
        return when (this) {
            is Workouts -> "Workouts_${selectedTabIndex}"
            is Settings -> "Settings"
            is ErrorLogs -> "ErrorLogs"
            is NewWorkout -> "NewWorkout_${workoutPlanId?.toString() ?: "null"}"
            is Workout -> "Workout_${workoutId}"
            is EditWorkout -> "EditWorkout_${workoutId}"
            is WorkoutDetail -> "WorkoutDetail_${workoutId}"
            is WorkoutHistory -> "WorkoutHistory_${workoutId}_${workoutHistoryId?.toString() ?: "null"}"
            is ExerciseDetail -> "ExerciseDetail_${workoutId}_${selectedExerciseId}"
            is ExerciseHistory -> "ExerciseHistory_${workoutId}_${selectedExerciseId}"
            is NewExercise -> "NewExercise_${workoutId}"
            is EditExercise -> "EditExercise_${workoutId}_${selectedExerciseId}"
            is NewSuperset -> "NewSuperset_${workoutId}"
            is EditSuperset -> "EditSuperset_${workoutId}_${selectedSupersetId}"
            is NewRest -> "NewRest_${workoutId}_${parentExerciseId?.toString() ?: "null"}"
            is EditRest -> "EditRest_${workoutId}_${selectedRest.id}"
            is NewRestSet -> "NewRestSet_${workoutId}_${parentExerciseId}"
            is EditRestSet -> "EditRestSet_${workoutId}_${selectedRestSet.id}_${parentExerciseId}"
            is InsertRestSetAfter -> "InsertRestSetAfter_${workoutId}_${exerciseId}_${afterSetId}"
            is InsertRestAfter -> "InsertRestAfter_${workoutId}_${afterComponentId}"
            is NewSet -> "NewSet_${workoutId}_${parentExerciseId}"
            is EditSet -> "EditSet_${workoutId}_${selectedSet.id}"
            is NewEquipment -> "NewEquipment_${equipmentType.name}"
            is EditEquipment -> "EditEquipment_${equipmentId}_${equipmentType.name}"
        }
    }
}

private fun emptyWorkoutStore(): WorkoutStore {
    return WorkoutStore(
        workouts = emptyList(),
        polarDeviceId = null,
        birthDateYear = 0,
        weightKg = 0.0,
        equipments = emptyList(),
        accessoryEquipments = emptyList(),
        workoutPlans = emptyList(),
        progressionPercentageAmount = 0.0,
        measuredMaxHeartRate = null,
        restingHeartRate = null
    )
}

private data class AppState(
    val workoutStore: WorkoutStore = emptyWorkoutStore(),
    val selectedWorkoutPlanId: UUID? = null
)

class AppViewModel(
    application: Application
) : AndroidViewModel(application) {
    companion object {
        private const val TAG = "AppViewModel"
        private const val DEBUG_TAG = "WorkoutHistDebug"
    }
    private var screenDataStack = mutableListOf<ScreenData>(ScreenData.Workouts(0))

    override fun onCleared() {
        super.onCleared()
        // #region agent log
        Log.d(DEBUG_TAG, "AppViewModel.onCleared ViewModelId=${System.identityHashCode(this)} viewModelScope cancelled")
        // #endregion
    }

    private val _state = MutableStateFlow(AppState())
    private val _isInitialDataLoaded = MutableStateFlow(false)
    private var _userAge = mutableIntStateOf(0)

    /**
     * Load workout store from disk asynchronously. Call once from the UI (e.g. NavHost).
     * When complete, [isInitialDataLoaded] becomes true.
     */
    fun loadWorkoutStore() {
        viewModelScope.launch {
            try {
                val app = getApplication<Application>()
                val repo = WorkoutStoreRepository(app.filesDir)
                val db = AppDatabase.getDatabase(app)
                val migrated = withContext(Dispatchers.IO) {
                    val store = repo.getWorkoutStore()
                    migrateWorkoutStoreSetIdsIfNeeded(store, db, repo)
                }
                setWorkoutStoreState(migrated, triggerSend = false)
                _isInitialDataLoaded.value = true
            } catch (e: Exception) {
                _isInitialDataLoaded.value = true
            }
        }
    }

    // Convert currentScreenData to a MutableState
    var currentScreenData: ScreenData by mutableStateOf(screenDataStack.lastOrNull() ?: ScreenData.Workouts(0))
        private set

    // Debouncer for workout saves
    private val saveDebouncer = WorkoutSaveDebouncer(viewModelScope, debounceDelayMs = 5000L)

    val userAge: State<Int> = _userAge

    val workoutStoreFlow: StateFlow<WorkoutStore> = _state
        .map { it.workoutStore }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = _state.value.workoutStore
        )

    val workoutsFlow: StateFlow<List<Workout>> = workoutStoreFlow
        .map { it.workouts }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = _state.value.workoutStore.workouts
        )

    val workoutPlansFlow: StateFlow<List<WorkoutPlan>> = workoutStoreFlow
        .map { sortWorkoutPlansWithUnassignedLast(it.workoutPlans) }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = _state.value.workoutStore.workoutPlans
        )

    val equipmentsFlow: StateFlow<List<WeightLoadedEquipment>> = workoutStoreFlow
        .map { it.equipments }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = _state.value.workoutStore.equipments
        )

    val accessoryEquipmentsFlow: StateFlow<List<AccessoryEquipment>> = workoutStoreFlow
        .map { it.accessoryEquipments }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = _state.value.workoutStore.accessoryEquipments
        )

    val selectedWorkoutPlanIdFlow: StateFlow<UUID?> = _state
        .map { it.selectedWorkoutPlanId }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = _state.value.selectedWorkoutPlanId
        )

    val workoutStore: WorkoutStore
        get() = _state.value.workoutStore

    private val _updateNotificationFlow = MutableStateFlow<String?>(null)
    val updateNotificationFlow = _updateNotificationFlow.asStateFlow()

    var selectedHomeTab by mutableIntStateOf(0)
        private set

    fun setSelectedWorkoutPlanId(planId: UUID?) {
        _state.update { current ->
            current.copy(selectedWorkoutPlanId = planId)
        }
    }

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

    val isInitialDataLoaded: StateFlow<Boolean> = _isInitialDataLoaded.asStateFlow()

    fun setInitialDataLoaded(loaded: Boolean) {
        _isInitialDataLoaded.value = loaded
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
    val effectiveSelectedWorkoutPlanIdFlow: StateFlow<UUID?> = combine(
        selectedWorkoutPlanIdFlow,
        workoutPlansFlow
    ) { selectedPlanId, plans ->
        selectedPlanId ?: plans.singleOrNull()
            ?.takeIf { isUnassignedPlan(it) }
            ?.id
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = _state.value.selectedWorkoutPlanId
    )

    private val _groupedWorkoutHistories = MutableStateFlow<Map<LocalDate, List<WorkoutHistory>>?>(null)
    val groupedWorkoutHistories: StateFlow<Map<LocalDate, List<WorkoutHistory>>?> = _groupedWorkoutHistories.asStateFlow()

    private val _workoutByIdForHistories = MutableStateFlow<Map<UUID, Workout>?>(null)
    val workoutByIdForHistories: StateFlow<Map<UUID, Workout>?> = _workoutByIdForHistories.asStateFlow()

    fun loadWorkoutHistories(enabledWorkouts: List<Workout>) {
        // #region agent log
        Log.d(DEBUG_TAG, "loadWorkoutHistories entry H1 enabledCount=${enabledWorkouts.size}")
        // #endregion
        refreshWorkoutHistories(enabledWorkouts)
    }

    private fun refreshWorkoutHistories(enabledWorkouts: List<Workout>) {
        val viewModelId = System.identityHashCode(this)
        viewModelScope.launch {
            // #region agent log
            Log.d(DEBUG_TAG, "refreshWorkoutHistories job started ViewModelId=$viewModelId")
            // #endregion
            try {
                val grouped = withContext(Dispatchers.IO) {
                    val db = AppDatabase.getDatabase(getApplication<Application>())
                    val workoutHistoryDao = db.workoutHistoryDao()
                    val setHistoryDao = db.setHistoryDao()
                    val all = workoutHistoryDao.getAllWorkoutHistories()
                    val workoutHistoryIdsWithSets = setHistoryDao.getAllSetHistories()
                        .mapNotNull { it.workoutHistoryId }
                        .toSet()
                    val filtered = all.filter { history ->
                        enabledWorkouts.any { it.id == history.workoutId } &&
                                workoutHistoryIdsWithSets.contains(history.id)
                    }
                    val groupedMap = filtered.groupBy { it.date }
                // #region agent log
                Log.d(DEBUG_TAG, "refreshWorkoutHistories H2 allCount=${all.size} enabledCount=${enabledWorkouts.size} groupedSize=${groupedMap.size}")
                // #endregion
                    groupedMap
                }
                val byId = enabledWorkouts.associateBy { it.id }
                _groupedWorkoutHistories.value = grouped
                _workoutByIdForHistories.value = byId
                // #region agent log
                Log.d(DEBUG_TAG, "refreshWorkoutHistories set groupedSize=${grouped.size}")
                // #endregion
            } catch (e: Exception) {
                // #region agent log
                Log.e(DEBUG_TAG, "refreshWorkoutHistories error ViewModelId=$viewModelId (ViewModel cleared = Activity destroyed; look for MainActivity.finish log for stack trace)", e)
                // #endregion
            }
        }
    }

    fun getEquipmentById(equipmentId: UUID): WeightLoadedEquipment? {
        return (equipments + generic).find { it.id == equipmentId }
    }

    fun getAccessoryEquipmentById(equipmentId: UUID): AccessoryEquipment? {
        return workoutStore.accessoryEquipments.find { it.id == equipmentId }
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
            setWorkoutStoreState(workoutStore.copy(workouts = value))
        }

    var equipments: List<WeightLoadedEquipment>
        get() = workoutStore.equipments
        private set(value) {
            setWorkoutStoreState(workoutStore.copy(equipments = value))
        }

    public val GENERIC_ID = UUID.fromString("babe5d97-a86d-4ec2-84b6-634034aa847c")
    private val generic = Generic(GENERIC_ID, name = "Generic")

    val equipmentsFlowWithGeneric: StateFlow<List<WeightLoadedEquipment>> = equipmentsFlow
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

    private fun adjustWorkouts(workouts: List<Workout>): List<Workout> {
        return workouts.map { workout ->
            val adjustedWorkoutComponents = workout.workoutComponents.map { workoutComponent ->
                when (workoutComponent) {
                    is Exercise -> workoutComponent.copy(
                        sets = ensureRestSeparatedBySets(workoutComponent.sets),
                        requiredAccessoryEquipmentIds = workoutComponent.requiredAccessoryEquipmentIds ?: emptyList()
                    )
                    is Superset -> workoutComponent.copy(exercises = workoutComponent.exercises.map { exercise ->
                        exercise.copy(
                            sets = ensureRestSeparatedBySets(exercise.sets),
                            requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList()
                        )
                    })
                    is Rest -> workoutComponent
                }
            }

            workout.copy(workoutComponents = ensureRestSeparatedByExercises(adjustedWorkoutComponents))
        }
    }

    private fun normalizeWorkoutStore(newWorkoutStore: WorkoutStore): WorkoutStore {
        val adjustedWorkouts = adjustWorkouts(newWorkoutStore.workouts)
        val dedupedPlans = newWorkoutStore.workoutPlans.distinctBy { it.id }
        val planIds = dedupedPlans.map { it.id }.toSet()
        val workoutsWithoutPlan = adjustedWorkouts.filter { workout ->
            workout.workoutPlanId == null || workout.workoutPlanId !in planIds
        }
        val existingUnassignedPlan = dedupedPlans.find { isUnassignedPlan(it) }
        val shouldCreateUnassigned = workoutsWithoutPlan.isNotEmpty()
        val unassignedPlanId = when {
            existingUnassignedPlan != null -> existingUnassignedPlan.id
            shouldCreateUnassigned -> UUID.randomUUID()
            else -> null
        }

        val normalizedWorkouts = if (unassignedPlanId != null) {
            adjustedWorkouts.map { workout ->
                if (workout.workoutPlanId == null || workout.workoutPlanId !in planIds) {
                    workout.copy(workoutPlanId = unassignedPlanId)
                } else {
                    workout
                }
            }
        } else {
            adjustedWorkouts
        }

        val basePlans = if (unassignedPlanId != null && existingUnassignedPlan == null) {
            val nextOrder = (dedupedPlans.maxOfOrNull { it.order } ?: -1) + 1
            dedupedPlans + WorkoutPlan(
                id = unassignedPlanId,
                name = UNASSIGNED_PLAN_NAME,
                workoutIds = emptyList(),
                order = nextOrder
            )
        } else {
            dedupedPlans
        }

        val workoutsByPlanId = normalizedWorkouts.groupBy { it.workoutPlanId }
        val updatedPlans = basePlans.map { plan ->
            val workoutIds = workoutsByPlanId[plan.id]?.map { it.id } ?: emptyList()
            plan.copy(workoutIds = workoutIds)
        }

        val cleanedPlans = updatedPlans.filter { plan ->
            isUnassignedPlan(plan) || plan.workoutIds.isNotEmpty()
        }

        return newWorkoutStore.copy(
            workouts = normalizedWorkouts,
            workoutPlans = cleanedPlans
        )
    }

    private fun setWorkoutStoreState(newWorkoutStore: WorkoutStore, triggerSend: Boolean = true) {
        val normalizedStore = normalizeWorkoutStore(newWorkoutStore)
        val currentYear = Calendar.getInstance().get(Calendar.YEAR)
        _userAge.intValue = currentYear - normalizedStore.birthDateYear
        val resolvedPlanId = resolveSelectedWorkoutPlanId(
            plans = normalizedStore.workoutPlans,
            workouts = normalizedStore.workouts,
            currentSelection = _state.value.selectedWorkoutPlanId
        )
        _state.update { current ->
            current.copy(
                workoutStore = normalizedStore,
                selectedWorkoutPlanId = resolvedPlanId
            )
        }
        if (triggerSend) {
            triggerMobile()
        }
    }

    private fun resolveSelectedWorkoutPlanId(
        plans: List<WorkoutPlan>,
        workouts: List<Workout>,
        currentSelection: UUID?
    ): UUID? {
        val planIds = plans.map { it.id }.toSet()
        if (currentSelection != null && currentSelection in planIds) {
            return currentSelection
        }

        val unassignedPlan = plans.find { isUnassignedPlan(it) }
        if (unassignedPlan != null) {
            val hasWorkouts = workouts.any { it.workoutPlanId == unassignedPlan.id }
            if (hasWorkouts || plans.size == 1) {
                return unassignedPlan.id
            }
        }

        return plans.minByOrNull { it.order }?.id
    }

    fun updateWorkoutStore(newWorkoutStore: WorkoutStore, triggerSend: Boolean = true) {
        val cleanedWorkoutStore = fixExercisesWithInvalidEquipmentIds(newWorkoutStore)
        setWorkoutStoreState(cleanedWorkoutStore, triggerSend)
    }
    
    /**
     * Retroactively fixes exercises that have non-existent equipment IDs assigned.
     * For WEIGHT exercises, sets equipmentId to GENERIC_ID if the equipment doesn't exist.
     * For other exercise types, sets equipmentId to null if the equipment doesn't exist.
     */
    private fun fixExercisesWithInvalidEquipmentIds(workoutStore: WorkoutStore): WorkoutStore {
        val validEquipmentIds = workoutStore.equipments.map { it.id }.toSet()
        val genericId = GENERIC_ID
        
        // Ensure GENERIC_ID is in the valid equipment list
        val allValidEquipmentIds = if (validEquipmentIds.contains(genericId)) {
            validEquipmentIds
        } else {
            validEquipmentIds + genericId
        }
        
        fun fixExerciseInComponents(components: List<WorkoutComponent>): List<WorkoutComponent> {
            return components.map { component ->
                when (component) {
                    is Exercise -> {
                        val needsFix = component.equipmentId != null && 
                                     !allValidEquipmentIds.contains(component.equipmentId)
                        if (needsFix) {
                            val fixedEquipmentId = when (component.exerciseType) {
                                ExerciseType.WEIGHT -> genericId
                                else -> null
                            }
                            component.copy(equipmentId = fixedEquipmentId)
                        } else {
                            component
                        }
                    }
                    is Superset -> {
                        val fixedExercises = component.exercises.map { exercise ->
                            val needsFix = exercise.equipmentId != null && 
                                         !allValidEquipmentIds.contains(exercise.equipmentId)
                            if (needsFix) {
                                val fixedEquipmentId = when (exercise.exerciseType) {
                                    ExerciseType.WEIGHT -> genericId
                                    else -> null
                                }
                                exercise.copy(equipmentId = fixedEquipmentId)
                            } else {
                                exercise
                            }
                        }
                        component.copy(exercises = fixedExercises)
                    }
                    else -> component
                }
            }
        }
        
        val fixedWorkouts = workoutStore.workouts.map { workout ->
            val fixedComponents = fixExerciseInComponents(workout.workoutComponents)
            workout.copy(workoutComponents = fixedComponents)
        }
        
        return workoutStore.copy(workouts = fixedWorkouts)
    }

    fun updateEquipments(newEquipments: List<WeightLoadedEquipment>) {
        equipments = newEquipments
    }

    var accessoryEquipments: List<AccessoryEquipment>
        get() = workoutStore.accessoryEquipments
        private set(value) {
            setWorkoutStoreState(workoutStore.copy(accessoryEquipments = value))
        }

    fun updateAccessoryEquipments(newAccessories: List<AccessoryEquipment>) {
        accessoryEquipments = newAccessories
    }

    fun updateWorkouts(newWorkouts: List<Workout>) {
        setWorkoutStoreState(workoutStore.copy(workouts = newWorkouts))
    }

    /**
     * Reorders workouts within a plan (or unassigned when planId is null).
     * Assigns order = index to each workout in newOrderedWorkouts and merges with workouts from other plans.
     */
    fun reorderWorkoutsInPlan(planId: UUID?, newOrderedWorkouts: List<Workout>) {
        val reordered = newOrderedWorkouts.mapIndexed { index, w -> w.copy(order = index) }
        val otherWorkouts = workouts.filter { it.workoutPlanId != planId }
        updateWorkouts(otherWorkouts + reordered)
    }

    fun deleteWorkoutsById(workoutIdsToDelete: kotlin.collections.Set<UUID>) {
        deleteWorkouts(workoutIdsToDelete)
    }

    fun deleteWorkouts(workoutIdsToDelete: kotlin.collections.Set<UUID>) {
        if (workoutIdsToDelete.isEmpty()) {
            return
        }

        val globalIdsToDelete = workouts
            .filter { it.id in workoutIdsToDelete }
            .map { it.globalId }
            .toSet()

        val remainingWorkouts = workouts
            .filterNot { workout ->
                workout.id in workoutIdsToDelete ||
                    (globalIdsToDelete.isNotEmpty() && workout.globalId in globalIdsToDelete)
            }
            .mapIndexed { index, workout -> workout.copy(order = index) }

        setWorkoutStoreState(workoutStore.copy(workouts = remainingWorkouts))
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
        conflictResolution: ConflictResolution = ConflictResolution.SKIP_DUPLICATES
    ) {
        val merged = mergeWorkoutStore(workoutStore, importedWorkoutStore, conflictResolution)
        updateWorkoutStore(merged)
    }

    // Workout Plan Helper Methods
    
    /**
     * Checks if a workout plan is the special "Unassigned" plan.
     * "Unassigned" is a system-managed plan that users cannot move workouts to.
     */
    fun isUnassignedPlan(plan: WorkoutPlan?): Boolean {
        return plan?.name == UNASSIGNED_PLAN_NAME
    }
    
    fun getWorkoutPlanById(planId: UUID): WorkoutPlan? {
        return workoutStore.workoutPlans.find { it.id == planId }
    }
    
    fun getAllWorkoutPlans(): List<WorkoutPlan> {
        // Safety net: deduplicate by ID before sorting to prevent displaying duplicates
        return sortWorkoutPlansWithUnassignedLast(workoutStore.workoutPlans.distinctBy { it.id })
    }

    private fun sortWorkoutPlansWithUnassignedLast(plans: List<WorkoutPlan>): List<WorkoutPlan> {
        return plans.sortedWith(
            compareBy<WorkoutPlan>(
                { isUnassignedPlan(it) },
                { it.order }
            )
        )
    }

    fun getSelectableWorkoutPlans(currentPlanId: UUID?): List<WorkoutPlan> {
        return getAllWorkoutPlans()
            .filter { plan ->
                plan.id != currentPlanId && !isUnassignedPlan(plan)
            }
    }
    
    fun getWorkoutsByPlan(planId: UUID?): List<Workout> {
        return if (planId == null) {
            workouts.filter { it.workoutPlanId == null }
        } else {
            workouts.filter { it.workoutPlanId == planId }
        }
    }
    
    fun updateWorkoutPlanName(planId: UUID, newName: String) {
        val updatedPlans = workoutStore.workoutPlans.map { plan ->
            if (plan.id == planId) {
                plan.copy(name = newName)
            } else {
                plan
            }
        }
        setWorkoutStoreState(workoutStore.copy(workoutPlans = updatedPlans))
    }

    fun moveWorkoutToPlan(workoutId: UUID, targetPlanId: UUID?) {
        moveWorkoutsToPlan(setOf(workoutId), targetPlanId)
    }

    fun moveWorkoutsToPlan(workoutIds: kotlin.collections.Set<UUID>, targetPlanId: UUID?) {
        if (workoutIds.isEmpty()) {
            return
        }

        if (targetPlanId != null) {
            val targetPlan = getWorkoutPlanById(targetPlanId) ?: return
            if (isUnassignedPlan(targetPlan)) {
                return
            }
        }

        val updatedWorkouts = workouts.map { workout ->
            if (workout.id in workoutIds) {
                workout.copy(workoutPlanId = targetPlanId)
            } else {
                workout
            }
        }

        setWorkoutStoreState(workoutStore.copy(workouts = updatedWorkouts))
    }
    
    fun getEquipmentForPlan(planId: UUID): List<WeightLoadedEquipment> {
        val planWorkouts = getWorkoutsByPlan(planId)
        val equipmentIds = mutableSetOf<UUID>()
        
        planWorkouts.forEach { workout ->
            workout.workoutComponents.forEach { component ->
                when (component) {
                    is Exercise -> {
                        component.equipmentId?.let { equipmentIds.add(it) }
                    }
                    is Superset -> {
                        component.exercises.forEach { exercise ->
                            exercise.equipmentId?.let { equipmentIds.add(it) }
                        }
                    }
                    is Rest -> { /* No equipment */ }
                }
            }
        }
        
        return workoutStore.equipments.filter { it.id in equipmentIds }
    }
    
    fun getAccessoriesForPlan(planId: UUID): List<AccessoryEquipment> {
        val planWorkouts = getWorkoutsByPlan(planId)
        val accessoryIds = mutableSetOf<UUID>()
        
        planWorkouts.forEach { workout ->
            workout.workoutComponents.forEach { component ->
                when (component) {
                    is Exercise -> {
                        component.requiredAccessoryEquipmentIds?.forEach { accessoryIds.add(it) }
                    }
                    is Superset -> {
                        component.exercises.forEach { exercise ->
                            exercise.requiredAccessoryEquipmentIds?.forEach { accessoryIds.add(it) }
                        }
                    }
                    is Rest -> { /* No accessories */ }
                }
            }
        }
        
        return workoutStore.accessoryEquipments.filter { it.id in accessoryIds }
    }
    
    fun addWorkoutPlan(plan: WorkoutPlan) {
        // Check if plan with same ID already exists (idempotent behavior)
        if (workoutStore.workoutPlans.any { it.id == plan.id }) {
            // Plan already exists, skip adding to prevent duplicates
            return
        }
        val updatedPlans = workoutStore.workoutPlans + plan
        setWorkoutStoreState(workoutStore.copy(workoutPlans = updatedPlans))
    }
    
    fun updateWorkoutPlan(updatedPlan: WorkoutPlan) {
        val updatedPlans = workoutStore.workoutPlans.map { plan ->
            if (plan.id == updatedPlan.id) {
                updatedPlan
            } else {
                plan
            }
        }
        setWorkoutStoreState(workoutStore.copy(workoutPlans = updatedPlans))
    }

    fun deleteWorkoutPlan(planId: UUID) {
        val plan = getWorkoutPlanById(planId) ?: return
        if (isUnassignedPlan(plan)) {
            return
        }

        val updatedWorkouts = workouts.map { workout ->
            if (workout.workoutPlanId == planId) {
                workout.copy(workoutPlanId = null)
            } else {
                workout
            }
        }

        val updatedPlans = workoutStore.workoutPlans.filter { it.id != planId }
        setWorkoutStoreState(
            workoutStore.copy(
                workouts = updatedWorkouts,
                workoutPlans = updatedPlans
            )
        )
    }
    
    /**
     * Deletes workout plans that become empty after workouts are deleted.
     * Only deletes non-"Unassigned" plans that have no remaining workouts.
     * 
     * @param affectedPlanIds List of plan IDs that may have become empty (should be collected before workouts are deleted)
     *                        This parameter is kept for backward compatibility but all plans are now checked.
     */
    fun deleteEmptyWorkoutPlans(@Suppress("UNUSED_PARAMETER") affectedPlanIds: List<UUID>) {
        setWorkoutStoreState(workoutStore)
    }

    /**
     * Schedules a debounced save of the workout store.
     * If a save is already scheduled, it cancels the previous one and schedules a new one.
     *
     * @param context The application context
     * @param workoutStoreRepository The repository for saving workout store
     * @param db The app database
     */
    fun scheduleWorkoutSave(
        context: Context,
        workoutStoreRepository: WorkoutStoreRepository,
        db: AppDatabase
    ) {
        viewModelScope.launch {
            saveDebouncer.schedule {
                // Never persist empty store before initial load completed (prevents overwriting file when Activity/ViewModel recreated and load not yet applied)
                if (workoutStore.workouts.isEmpty() && !_isInitialDataLoaded.value) {
                    return@schedule
                }
                saveWorkoutStoreWithBackup(context, workoutStore, workoutStoreRepository, db)
            }
        }
    }

    /**
     * Schedules a debounced save of the workout store using context-only version.
     * Use this in composables where you only have access to context.
     *
     * @param context The application context
     */
    fun scheduleWorkoutSave(context: Context) {
        viewModelScope.launch {
            saveDebouncer.schedule {
                // Never persist empty store before initial load completed (prevents overwriting file when Activity/ViewModel recreated and load not yet applied)
                if (workoutStore.workouts.isEmpty() && !_isInitialDataLoaded.value) {
                    return@schedule
                }
                saveWorkoutStoreWithBackupFromContext(context, workoutStore)
            }
        }
    }

    /**
     * Immediately executes any pending debounced save operation.
     * Only saves if a save was actually scheduled via scheduleWorkoutSave().
     * If no save is pending, this is a no-op.
     *
     * @param context The application context
     * @param workoutStoreRepository The repository for saving workout store
     * @param db The app database
     */
    suspend fun flushWorkoutSave(
        context: Context,
        workoutStoreRepository: WorkoutStoreRepository,
        db: AppDatabase
    ) {
        // Only flush if there's a pending save - flush() is a no-op if no save is scheduled
        saveDebouncer.flush()
    }

    /**
     * Immediately executes any pending debounced save operation using context-only version.
     * Only saves if a save was actually scheduled via scheduleWorkoutSave().
     * If no save is pending, this is a no-op.
     *
     * @param context The application context
     */
    suspend fun flushWorkoutSave(context: Context) {
        // Only flush if there's a pending save - flush() is a no-op if no save is scheduled
        saveDebouncer.flush()
    }
}
