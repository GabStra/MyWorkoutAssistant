package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import android.util.Log
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.addSetToExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.removeSetsFromExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutComponentsRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.coroutines.DefaultDispatcherProvider
import com.gabstra.myworkoutassistant.shared.coroutines.DispatcherProvider
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.getNewSet
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
import com.gabstra.myworkoutassistant.shared.removeRestAndRestPause
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.utils.PlateauDetectionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlanner
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlateOptimizer
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.DayOfWeek
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.temporal.TemporalAdjusters
import java.util.Calendar
import java.util.LinkedList
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue

private class ResettableLazy<T>(private val initializer: () -> T) {
    private var _value: T? = null
    private var initialized = false

    fun getValue(): T {
        if (!initialized) {
            _value = initializer()
            initialized = true
        }
        return _value!!
    }

    fun reset() {
        _value = null
        initialized = false
    }
}

open class WorkoutViewModel(
    protected val dispatchers: DispatcherProvider = DefaultDispatcherProvider,
    private val executedSetStore: ExecutedSetStore = DefaultExecutedSetStore()
) : ViewModel() {
    private var storeSetDataJob: Job? = null

    private val _keepScreenOn = mutableStateOf(false)
    val keepScreenOn: State<Boolean> = _keepScreenOn

    private val _currentScreenDimmingState = mutableStateOf(false)

    val currentScreenDimmingState: State<Boolean> = _currentScreenDimmingState
    private val _lightScreenUp = Channel<Unit>(Channel.BUFFERED)
    val lightScreenUp = _lightScreenUp.receiveAsFlow()

    val enableDimming: State<Boolean> = derivedStateOf {
        !isPaused.value && currentScreenDimmingState.value && !keepScreenOn.value
    }

    fun toggleKeepScreenOn() {
        _keepScreenOn.value = !_keepScreenOn.value
        rebuildScreenState()
    }

    fun setDimming(shouldDim: Boolean) {
        _currentScreenDimmingState.value = shouldDim
        rebuildScreenState()
    }

    fun lightScreenUp() {
        viewModelScope.launch(dispatchers.main) {
            _lightScreenUp.send(Unit)
        }
    }

    fun reEvaluateDimmingForCurrentState() {
        val currentState = workoutState.value
        if (currentState is WorkoutState.Set) {
            val exercise = exercisesById[currentState.exerciseId]!!
            _currentScreenDimmingState.value = !exercise.keepScreenOn
        } else if (currentState is WorkoutState.Rest) {
            _currentScreenDimmingState.value = true
        }
        rebuildScreenState()
    }

    var workoutStore by mutableStateOf(
        WorkoutStore(
            workouts = emptyList(),
            polarDeviceId = null,
            birthDateYear = 0,
            weightKg = 0.0,
            equipments = emptyList(),
            workoutPlans = emptyList(),
            progressionPercentageAmount = 0.0,
        )
    )

    var lastSessionWorkout by mutableStateOf<Workout?>(null)

    fun getEquipmentById(id: UUID): WeightLoadedEquipment? {
        return workoutStore.equipments.find { it.id == id }
    }

    fun getAccessoryEquipmentById(id: UUID): AccessoryEquipment? {
        return workoutStore.accessoryEquipments.find { it.id == id }
    }

    private val _isPaused = mutableStateOf(false) // Private mutable state
    open val isPaused: State<Boolean> = _isPaused // read-only State access

    fun pauseWorkout() {
        _isPaused.value = true
        rebuildScreenState()
    }

    fun resumeWorkout() {
        _isPaused.value = false
        rebuildScreenState()
    }

    private val _workouts = MutableStateFlow<List<Workout>>(emptyList())
    val workouts = _workouts.asStateFlow()

    private var _userAge = mutableIntStateOf(0)
    val userAge: State<Int> = _userAge

    private var _bodyWeight = mutableStateOf(0.0)
    val bodyWeight: State<Double> = _bodyWeight

    private var _backupProgress = mutableStateOf(0f)
    val backupProgress: State<Float> = _backupProgress

    private var _selectedWorkoutId = mutableStateOf<UUID?>(null)
    val selectedWorkoutId: State<UUID?> get() = _selectedWorkoutId

    // Create a function to update the backup progress
    fun setBackupProgress(progress: Float) {
        _backupProgress.value = progress
    }

    open val allWorkoutStates: MutableList<WorkoutState> = mutableListOf()

    var polarDeviceId: String = ""
        get() = workoutStore.polarDeviceId ?: ""

    fun resetWorkoutStore() {
        updateWorkoutStore(
            WorkoutStore(
                workouts = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0.0,
                equipments = emptyList(),
                workoutPlans = emptyList(),
                progressionPercentageAmount = 0.0,
            )
        )
    }

    fun updateWorkoutStore(newWorkoutStore: WorkoutStore) {
        workoutStore = newWorkoutStore
        _workouts.value = workoutStore.workouts.filter { it.enabled && it.isActive }
        val currentYear = Calendar.getInstance().get(Calendar.YEAR)
        _userAge.intValue = currentYear - workoutStore.birthDateYear
        _bodyWeight.value = workoutStore.weightKg.toDouble()
        rebuildScreenState()
    }

    fun initExerciseHistoryDao(context: Context) {
        val db = AppDatabase.getDatabase(context)
        setHistoryDao = db.setHistoryDao()
    }

    fun initWorkoutHistoryDao(context: Context) {
        val db = AppDatabase.getDatabase(context)
        workoutHistoryDao = db.workoutHistoryDao()
    }

    fun initWorkoutScheduleDao(context: Context) {
        val db = AppDatabase.getDatabase(context)
        workoutScheduleDao = db.workoutScheduleDao()
    }

    fun initWorkoutRecordDao(context: Context) {
        val db = AppDatabase.getDatabase(context)
        workoutRecordDao = db.workoutRecordDao()
    }

    fun initExerciseInfoDao(context: Context) {
        val db = AppDatabase.getDatabase(context)
        exerciseInfoDao = db.exerciseInfoDao()
    }

    fun initExerciseSessionProgressionDao(context: Context) {
        val db = AppDatabase.getDatabase(context)
        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
    }

    fun initWorkoutStoreRepository(workoutStoreRepository: WorkoutStoreRepository) {
        this.workoutStoreRepository = workoutStoreRepository
    }

    private val _selectedWorkout = mutableStateOf(
        Workout(
            UUID.randomUUID(),
            "",
            "",
            listOf(),
            0,
            true,
            creationDate = LocalDate.now(),
            type = 0,
            globalId = UUID.randomUUID()
        )
    )
    val selectedWorkout: State<Workout> get() = _selectedWorkout

    protected lateinit var workoutRecordDao: WorkoutRecordDao

    protected lateinit var workoutHistoryDao: WorkoutHistoryDao

    protected lateinit var workoutScheduleDao: WorkoutScheduleDao

    protected lateinit var setHistoryDao: SetHistoryDao

    protected lateinit var exerciseInfoDao: ExerciseInfoDao

    protected lateinit var exerciseSessionProgressionDao: ExerciseSessionProgressionDao

    protected lateinit var workoutStoreRepository: WorkoutStoreRepository

    private val _workoutState =
        MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()

    private val _nextWorkoutState =
        MutableStateFlow<WorkoutState?>(null)
    val nextWorkoutState = _nextWorkoutState.asStateFlow()

    /**
     * Read-only access to executed sets history for external consumers.
     * Returns an immutable snapshot of the current state.
     */
    val executedSetsHistory: List<SetHistory>
        get() = executedSetStore.executedSets.value

    /**
     * StateFlow for observing executed sets history changes.
     * Use this in composables that need to react to changes.
     */
    val executedSetsHistoryFlow = executedSetStore.executedSets

    protected val heartBeatHistory: ConcurrentLinkedQueue<Int> = ConcurrentLinkedQueue()

    /**
     * State machine managing workout state progression.
     * Replaces manual queue/history management.
     */
    private var stateMachine: WorkoutStateMachine? = null

    /**
     * Read-only access to workout state history for external consumers.
     * Returns an immutable snapshot of the current history.
     */
    val workoutStateHistory: List<WorkoutState>
        get() = stateMachine?.history ?: emptyList()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    protected val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    val latestSetHistoriesByExerciseId: MutableMap<UUID, List<SetHistory>> = mutableMapOf()

    /**
     * Initializes the state machine from a list of workout states.
     * Filters out trailing Rest states and adds Completed state.
     * 
     * @param workoutStates The list of workout states to initialize from
     * @param startIndex The index to start at (defaults to 0)
     */
    private fun initializeStateMachine(workoutStates: List<WorkoutState>, startIndex: Int = 0): WorkoutStateMachine {
        val filteredStates = workoutStates.toMutableList()
        
        // Remove trailing Rest state if present
        if (filteredStates.isNotEmpty() && filteredStates.last() is WorkoutState.Rest) {
            filteredStates.removeAt(filteredStates.size - 1)
        }
        
        // Add Completed state if startWorkoutTime is set
        if (startWorkoutTime != null) {
            filteredStates.add(WorkoutState.Completed(startWorkoutTime!!))
        }
        
        // Adjust startIndex if Completed state was added
        val adjustedStartIndex = if (startWorkoutTime != null && startIndex >= filteredStates.size - 1) {
            // If startIndex points to the last state before Completed was added, adjust it
            filteredStates.size - 1
        } else {
            startIndex.coerceIn(0, filteredStates.size - 1)
        }
        
        return WorkoutStateMachine.fromStates(filteredStates, { LocalDateTime.now() }, adjustedStartIndex)
    }

    /**
     * Updates the state flows from the current state machine.
     */
    private fun updateStateFlowsFromMachine() {
        val machine = stateMachine
        if (machine != null) {
            _workoutState.value = machine.currentState
            _nextWorkoutState.value = machine.upcomingNext
            _isHistoryEmpty.value = machine.isHistoryEmpty
        }
        rebuildScreenState()
    }

    /**
     * Rebuilds the WorkoutScreenState from current ViewModel fields.
     * Call this whenever any UI-observable field changes.
     */
    protected open fun rebuildScreenState() {
        _screenState.value = WorkoutScreenState(
            workoutState = _workoutState.value,
            nextWorkoutState = _nextWorkoutState.value,
            selectedWorkout = _selectedWorkout.value,
            isPaused = _isPaused.value,
            hasWorkoutRecord = _hasWorkoutRecord.value,
            isResuming = _isResuming.value,
            isRefreshing = _isRefreshing.value,
            isCustomDialogOpen = _isCustomDialogOpen.value,
            enableWorkoutNotificationFlow = _enableWorkoutNotificationFlow.value,
            userAge = _userAge.intValue,
            startWorkoutTime = startWorkoutTime,
            enableDimming = enableDimming.value,
            keepScreenOn = _keepScreenOn.value,
            currentScreenDimmingState = _currentScreenDimmingState.value,
            headerDisplayMode = 0, // Default for base WorkoutViewModel, overridden in AppViewModel
            hrDisplayMode = 0, // Default for base WorkoutViewModel, overridden in AppViewModel
        )
    }

    val latestSetHistoryMap: MutableMap<UUID, SetHistory> = mutableMapOf()

    protected val weightsByEquipment: MutableMap<WeightLoadedEquipment, kotlin.collections.Set<Double>> =
        mutableMapOf()

    // Cache for available totals (getWeightsCombinationsNoExtra results) per equipment ID
    private val availableTotalsCache: MutableMap<UUID, kotlin.collections.Set<Double>> =
        mutableMapOf()

    fun getWeightByEquipment(equipment: WeightLoadedEquipment?): kotlin.collections.Set<Double> {
        if (equipment == null) return emptySet()
        return weightsByEquipment[equipment] ?: emptySet()
    }

    private fun getCachedAvailableTotals(equipment: WeightLoadedEquipment): kotlin.collections.Set<Double> {
        return availableTotalsCache.getOrPut(equipment.id) {
            equipment.getWeightsCombinationsNoExtra()
        }
    }

    val exerciseProgressionByExerciseId: MutableMap<UUID, Pair<DoubleProgressionHelper.Plan, ProgressionState>> =
        mutableMapOf()

    val plateauReasonByExerciseId: MutableMap<UUID, String?> =
        mutableMapOf()

    protected var currentWorkoutHistory by mutableStateOf<WorkoutHistory?>(null)

    var startWorkoutTime by mutableStateOf<LocalDateTime?>(null)

    var exercisesById: Map<UUID, Exercise> = emptyMap()
    var supersetIdByExerciseId: Map<UUID, UUID> = emptyMap()
    var exercisesBySupersetId: Map<UUID, List<Exercise>> = emptyMap()

    fun initializeExercisesMaps(selectedWorkout: Workout) {
        val orderedExercises = mutableListOf<Exercise>()

        selectedWorkout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> orderedExercises.add(component)
                is Superset -> orderedExercises.addAll(component.exercises)
                is Rest -> Unit
            }
        }

        exercisesById = orderedExercises.associateBy { it.id }

        supersetIdByExerciseId = selectedWorkout.workoutComponents
            .filterIsInstance<Superset>()
            .flatMap { superset ->
                superset.exercises.map { it.id to superset.id }
            }.toMap()

        exercisesBySupersetId = selectedWorkout.workoutComponents
            .filterIsInstance<Superset>()
            .associate { superset ->
                superset.id to superset.exercises
            }
    }

    val setsByExerciseId: Map<UUID, List<WorkoutState.Set>>
        get() = setStates
            .groupBy { it.exerciseId }
            .mapValues { (_, sets) ->
                sets.distinctBy { it.set.id }
            }

    protected var _workoutRecord by mutableStateOf<WorkoutRecord?>(null)
    protected var pendingResumeWorkoutHistoryId: UUID? = null

    private val _isResuming = MutableStateFlow<Boolean>(false)
    val isResuming = _isResuming.asStateFlow()

    private val _isRefreshing = MutableStateFlow<Boolean>(false)
    val isRefreshing = _isRefreshing.asStateFlow()

    private val _hasWorkoutRecord = MutableStateFlow<Boolean>(false)
    val hasWorkoutRecord = _hasWorkoutRecord.asStateFlow()

    private val _isCheckingWorkoutRecord = MutableStateFlow<Boolean>(false)
    val isCheckingWorkoutRecord = _isCheckingWorkoutRecord.asStateFlow()

    private val _hasExercises = MutableStateFlow<Boolean>(false)
    val hasExercises = _hasExercises.asStateFlow()

    private val _isCustomDialogOpen = MutableStateFlow<Boolean>(false)

    open val isCustomDialogOpen = _isCustomDialogOpen.asStateFlow()

    private val _enableWorkoutNotificationFlow = MutableStateFlow<String?>(null)
    val enableWorkoutNotificationFlow = _enableWorkoutNotificationFlow.asStateFlow()

    protected val _screenState = MutableStateFlow<WorkoutScreenState>(WorkoutScreenState.initial())
    val screenState = _screenState.asStateFlow()

    fun triggerWorkoutNotification() {
        _enableWorkoutNotificationFlow.value = System.currentTimeMillis().toString()
        rebuildScreenState()
    }

    // Setter method to open dialog
    fun openCustomDialog() {
        _isCustomDialogOpen.value = true
        rebuildScreenState()
    }

    // Setter method to close dialog
    fun closeCustomDialog() {
        _isCustomDialogOpen.value = false
        rebuildScreenState()
    }


    fun setSelectedWorkoutId(workoutId: UUID) {
        val workout = workoutStore.workouts.find { it.id == workoutId }
            ?: workouts.value.find { it.id == workoutId }

        pendingResumeWorkoutHistoryId = null
        _selectedWorkoutId.value = workoutId

        if (workout == null) {
            Log.w("WorkoutViewModel", "Workout not found for id: $workoutId")
            _hasExercises.value = false
            _hasWorkoutRecord.value = false
            _isCheckingWorkoutRecord.value = false
            exercisesById = emptyMap()
            supersetIdByExerciseId = emptyMap()
            exercisesBySupersetId = emptyMap()
            rebuildScreenState()
            return
        }

        _hasExercises.value = workout.workoutComponents.filter { it.enabled }.isNotEmpty()

        initializeExercisesMaps(workout)
        getWorkoutRecord(workout)
    }

    fun resetAll() {
        resetWorkoutStore()
        workoutStoreRepository.saveWorkoutStore(workoutStore)
        viewModelScope.launch(dispatchers.main) {
            withContext(dispatchers.io) {
                workoutHistoryDao.deleteAll()
                setHistoryDao.deleteAll()
                exerciseInfoDao.deleteAll()
                workoutRecordDao.deleteAll()
                workoutScheduleDao.deleteAll()
                exerciseInfoDao.deleteAll()
            }
        }
    }

    protected open fun getWorkoutRecord(workout: Workout) {
        _isCheckingWorkoutRecord.value = true
        viewModelScope.launch(dispatchers.main) {
            withContext(dispatchers.io) {
                _workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                if (_workoutRecord != null) {
                    val workoutHistory = workoutHistoryDao.getWorkoutHistoryById(_workoutRecord!!.workoutHistoryId)
                    if (workoutHistory == null) {
                        // Workout record exists but history doesn't - delete the orphaned record
                        workoutRecordDao.deleteById(_workoutRecord!!.id)
                        _workoutRecord = null
                        _hasWorkoutRecord.value = false
                    } else {
                        _hasWorkoutRecord.value = true
                    }
                } else {
                    _hasWorkoutRecord.value = false
                }
            }
            _isCheckingWorkoutRecord.value = false
            rebuildScreenState()
        }
    }

    fun upsertWorkoutRecord(exerciseId : UUID,setIndex: UInt) {
        viewModelScope.launch(dispatchers.io) {
            if (_workoutRecord == null) {
                _workoutRecord = WorkoutRecord(
                    id = UUID.randomUUID(),
                    workoutId = selectedWorkout.value.id,
                    exerciseId = exerciseId,
                    setIndex = setIndex,
                    workoutHistoryId = currentWorkoutHistory!!.id
                )
            } else {
                _workoutRecord = _workoutRecord!!.copy(
                    exerciseId = exerciseId,
                    setIndex = setIndex,
                )
            }

            workoutRecordDao.insert(_workoutRecord!!)

            _hasWorkoutRecord.value = true
            rebuildScreenState()
        }
    }

    fun deleteWorkoutRecord() {
        viewModelScope.launch(dispatchers.io) {
            _workoutRecord?.let {
                workoutRecordDao.deleteById(it.id)
                _workoutRecord = null
                _hasWorkoutRecord.value = false
            }
        }
    }

    data class IncompleteWorkout(
        val workoutHistory: WorkoutHistory,
        val workoutName: String,
        val workoutId: UUID
    )

    suspend fun getIncompleteWorkouts(): List<IncompleteWorkout> {
        return withContext(dispatchers.io) {
            val incompleteHistories = workoutHistoryDao.getAllUnfinishedWorkoutHistories(isDone = false)
            
            // Group by workoutId and get the most recent one for each workout
            val groupedByWorkoutId = incompleteHistories
                .groupBy { it.workoutId }
                .mapValues { (_, histories) ->
                    histories.maxByOrNull { it.startTime } ?: histories.first()
                }
            
            // Map to IncompleteWorkout with workout name
            groupedByWorkoutId.values.mapNotNull { workoutHistory ->
                val workout = workoutStore.workouts.find { it.id == workoutHistory.workoutId }
                    ?: workoutStore.workouts.find { it.globalId == workoutHistory.globalId }

                if (workout == null) {
                    return@mapNotNull null
                }

                val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                if (workoutRecord == null || workoutRecord.workoutHistoryId != workoutHistory.id) {
                    return@mapNotNull null
                }

                IncompleteWorkout(
                    workoutHistory = workoutHistory,
                    workoutName = workout.name,
                    workoutId = workout.id
                )
            }
        }
    }

    /**
     * Finds the resumption index for a workout.
     * 
     * Primary approach: Uses WorkoutRecord to find the exact state matching exerciseId and setIndex.
     * Fallback approach: If WorkoutRecord doesn't match, uses SetHistory to find the first incomplete set.
     * 
     * @param allWorkoutStates The list of all workout states
     * @param executedSetsHistorySnapshot The snapshot of executed set histories
     * @return The index to resume at, or 0 if no match found
     */
    private fun findResumptionIndex(
        allWorkoutStates: List<WorkoutState>,
        executedSetsHistorySnapshot: List<SetHistory>
    ): Int {
        // Primary approach: Use WorkoutRecord (always available when resuming)
        if (_workoutRecord != null) {
            val workoutRecord = _workoutRecord!!
            
            // Find the state matching the WorkoutRecord's exerciseId and setIndex
            allWorkoutStates.forEachIndexed { index, state ->
                when (state) {
                    is WorkoutState.Set -> {
                        if (state.exerciseId == workoutRecord.exerciseId && 
                            state.setIndex == workoutRecord.setIndex) {
                            return index
                        }
                    }
                    is WorkoutState.Rest -> {
                        // For Rest states, check if the previous Set state matches
                        if (index > 0) {
                            val previousState = allWorkoutStates[index - 1]
                            if (previousState is WorkoutState.Set &&
                                previousState.exerciseId == workoutRecord.exerciseId &&
                                previousState.setIndex == workoutRecord.setIndex) {
                                return index
                            }
                        }
                    }
                    else -> { /* Skip other states */ }
                }
            }
            
            // WorkoutRecord exists but doesn't match any state - fall back to SetHistory approach
            // This can happen if: workout structure changed, exercise removed, setIndex out of bounds, data inconsistency
        }
        
        // Fallback approach: Use SetHistory to find first incomplete set
        // Only used if WorkoutRecord doesn't match any state (rare edge cases)
        var firstSetWithHistoryIndex: Int? = null
        
        allWorkoutStates.forEachIndexed { index, state ->
            when (state) {
                is WorkoutState.Set -> {
                    val exercise = exercisesById[state.exerciseId]
                    // Only check exercises that store history (doNotStoreHistory = false)
                    if (exercise != null && !exercise.doNotStoreHistory) {
                        // Track the first set that stores history
                        if (firstSetWithHistoryIndex == null) {
                            firstSetWithHistoryIndex = index
                        }
                        
                        // Match by both setId AND order (not just setId)
                        val matchingSetHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                            setHistory.setId == state.set.id && setHistory.order == state.setIndex
                        }
                        // If no matching SetHistory entry exists, this is the first incomplete set
                        if (matchingSetHistory == null) {
                            return index
                        }
                    }
                }
                is WorkoutState.Rest -> {
                    val exercise = state.exerciseId?.let { exercisesById[it] }
                    // Only check exercises that store history (doNotStoreHistory = false)
                    if (exercise != null && !exercise.doNotStoreHistory) {
                        // Match by both setId AND order (not just setId)
                        val matchingSetHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                            setHistory.setId == state.set.id && setHistory.order == state.order
                        }
                        // If no matching SetHistory entry exists, this is the first incomplete set
                        if (matchingSetHistory == null) {
                            return index
                        }
                    }
                }
                else -> { /* Skip other states */ }
            }
        }
        
        // If all sets that store history have matching SetHistory entries, check what to return
        return if (executedSetsHistorySnapshot.isEmpty()) {
            // No executed sets exist - start from beginning
            0
        } else if (firstSetWithHistoryIndex != null) {
            // All sets with history are complete - return the last index (should be Completed state)
            (allWorkoutStates.size - 1).coerceAtLeast(0)
        } else {
            // All exercises have doNotStoreHistory = true - can't determine from SetHistory
            // This shouldn't happen if WorkoutRecord exists, but as a safety fallback, start from beginning
            0
        }
    }

    open fun resumeWorkoutFromRecord(onEnd: suspend () -> Unit = {}) {
        viewModelScope.launch(dispatchers.main) {
            withContext(dispatchers.io) {
                _enableWorkoutNotificationFlow.value = null
                _currentScreenDimmingState.value = false

                val preparingState = WorkoutState.Preparing(dataLoaded = false)

                _workoutState.value = preparingState
                stateMachine = null
                setStates.clear()
                allWorkoutStates.clear()
                weightsByEquipment.clear()
                _isPaused.value = false
                _selectedWorkout.value = _workouts.value.find { it.id == _selectedWorkoutId.value }!!
                rebuildScreenState()

                val resumeHistoryId = pendingResumeWorkoutHistoryId ?: _workoutRecord?.workoutHistoryId
                if (resumeHistoryId == null) {
                    pendingResumeWorkoutHistoryId = null
                    withContext(dispatchers.main) {
                        _hasWorkoutRecord.value = false
                        rebuildScreenState()
                    }
                    return@withContext
                }

                val resumeWorkoutHistory = workoutHistoryDao.getWorkoutHistoryById(resumeHistoryId)
                if (resumeWorkoutHistory == null) {
                    Log.e("WorkoutViewModel", "Workout history $resumeHistoryId not found when resuming")
                    pendingResumeWorkoutHistoryId = null
                    _workoutRecord = null
                    withContext(dispatchers.main) {
                        _hasWorkoutRecord.value = false
                        rebuildScreenState()
                    }
                    return@withContext
                }

                currentWorkoutHistory = resumeWorkoutHistory
                pendingResumeWorkoutHistoryId = null

                heartBeatHistory.addAll(currentWorkoutHistory!!.heartBeatRecords)
                
                // Calculate actual elapsed workout time from completed set histories
                // This ensures the timer shows only actual workout time, excluding time when app was closed
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(currentWorkoutHistory!!.id)
                val completedSetHistories = setHistories.filter { it.startTime != null && it.endTime != null }
                val totalElapsedSeconds = completedSetHistories.sumOf { 
                    Duration.between(it.startTime!!, it.endTime!!).seconds 
                }
                
                // Adjust startWorkoutTime so that Duration.between(startWorkoutTime, now) equals actual workout time
                startWorkoutTime = LocalDateTime.now().minusSeconds(totalElapsedSeconds)

                restoreExecutedSets()
                loadWorkoutHistory()

                preProcessExercises()
                generateProgressions()
                applyProgressions()
                val workoutStates = generateWorkoutStates()

                // Take a snapshot of executedSetsHistory (immutable from StateFlow)
                val executedSetsHistorySnapshot = executedSetStore.executedSets.value

                workoutStates.forEachIndexed { index, it ->
                    if (index == workoutStates.lastIndex && it is WorkoutState.Rest) {
                        return@forEachIndexed
                    }

                    if(it is WorkoutState.Set){
                        // Match by both setId AND order (not just setId) to handle unilateral exercises correctly
                        val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory -> 
                            setHistory.setId == it.set.id && setHistory.order == it.setIndex 
                        }
                        if(setHistory != null){
                            it.currentSetData = setHistory.setData
                        }
                    }

                    if(it is WorkoutState.Rest){
                        // Match by both setId AND order (not just setId) to handle unilateral exercises correctly
                        val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory -> 
                            setHistory.setId == it.set.id && setHistory.order == it.order 
                        }
                        if(setHistory != null){
                            it.currentSetData = setHistory.setData
                        }
                    }

                    allWorkoutStates.add(it)
                    if(it is WorkoutState.Set){
                        setStates.addLast(it)
                    }
                }

                // Find the resumption index using WorkoutRecord (primary) or SetHistory (fallback)
                val resumptionIndex = findResumptionIndex(allWorkoutStates, executedSetsHistorySnapshot)
                
                // Initialize state machine with all states at the correct resumption index
                stateMachine = initializeStateMachine(allWorkoutStates, resumptionIndex)
                updateStateFlowsFromMachine()
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
                triggerWorkoutNotification()
                onEnd()
            }
        }
    }

    fun getAllExerciseWorkoutStates(exerciseId: UUID): List<WorkoutState.Set> {
        return allWorkoutStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }
    }

    suspend fun createStatesFromExercise(exercise: Exercise): List<WorkoutState> {
        return addStatesFromExercise(exercise)
    }

    fun getAllExerciseCompletedSetsBefore(target: WorkoutState.Set): List<WorkoutState.Set> {
        // Find all indices where sets with matching set.id appear
        val matchingIndices = allWorkoutStates.mapIndexedNotNull { index, state ->
            if (state is WorkoutState.Set && state.set.id == target.set.id) {
                index
            } else null
        }
        
        if (matchingIndices.isEmpty()) return emptyList()
        
        // Determine which occurrence corresponds to the current position in workout flow
        val currentWorkoutState = _workoutState.value
        
        // Count how many matching sets have been completed (are in history)
        // This tells us which occurrence we're currently on (0-indexed)
        val completedMatchingSetsCount = workoutStateHistory.count { 
            it is WorkoutState.Set && it.set.id == target.set.id 
        }
        
        val cutoff: Int = if (target === currentWorkoutState) {
            // If target is the current state, use the occurrence index based on completed count
            // For unilateral sets: if 0 completed, we're on first occurrence; if 1 completed, we're on second
            val occurrenceIndex = completedMatchingSetsCount.coerceAtMost(matchingIndices.size - 1)
            matchingIndices[occurrenceIndex]
        } else {
            // If target is not the current state, determine its position
            // Match by Set ID for WorkoutState.Set and WorkoutState.Rest, fallback to reference equality
            val targetIndexInHistory = workoutStateHistory.indexOfFirst { state ->
                when {
                    state is WorkoutState.Set && target is WorkoutState.Set -> state.set.id == target.set.id
                    state is WorkoutState.Rest && target is WorkoutState.Rest -> state.set.id == target.set.id
                    else -> state === target
                }
            }
            if (targetIndexInHistory >= 0) {
                // Target is in history, so it's been completed
                // Count how many matching sets appear before target in history
                val matchingSetsBeforeTargetInHistory = workoutStateHistory
                    .subList(0, targetIndexInHistory)
                    .count { it is WorkoutState.Set && it.set.id == target.set.id }
                // Use the occurrence index that corresponds to this position
                val occurrenceIndex = matchingSetsBeforeTargetInHistory.coerceAtMost(matchingIndices.size - 1)
                matchingIndices[occurrenceIndex]
            } else {
                // Target is not in history and not current, so it's upcoming
                // Use the first occurrence that hasn't been reached yet
                matchingIndices.first()
            }
        }
        
        if (cutoff <= 0) return emptyList()

        // Get all sets before the cutoff and deduplicate by set.id
        return allWorkoutStates
            .subList(0, cutoff)
            .filterIsInstance<WorkoutState.Set>()
            .distinctBy { it.set.id }
        //.filter { it.set !is RestSet } // uncomment to exclude rest sets
    }


    fun getAllExecutedSetsByExerciseId(exerciseId: UUID): List<SetHistory> {
        // Use store's convenience method which returns an immutable snapshot
        return executedSetStore.getAllByExerciseId(exerciseId)
    }

    fun getAllSetHistoriesByExerciseId(exerciseId: UUID): List<SetHistory> {
        return latestSetHistoriesByExerciseId[exerciseId] ?: emptyList()
    }

    /**
     * Gets the actual executed sets from the last completed workout for a given exercise.
     * Returns null if no completed workout exists.
     */
    suspend fun getLastCompletedWorkoutExecutedSets(exerciseId: UUID): List<SimpleSet>? {
        return withContext(dispatchers.io) {
            // Get all completed workouts for this workout template, sorted by most recent first
            val workoutHistories = workoutHistoryDao
                .getAllWorkoutHistories()
                .filter { 
                    it.globalId == selectedWorkout.value.globalId && 
                    it.isDone &&
                    // Exclude current workout if resuming
                    it.id != currentWorkoutHistory?.id
                }
                .sortedWith(compareByDescending<WorkoutHistory> { it.date }.thenByDescending { it.time })

            if (workoutHistories.isEmpty()) {
                return@withContext null
            }

            // Get the most recent completed workout
            val lastCompletedWorkoutHistory = workoutHistories.first()

            // Get SetHistories for this exercise from the last completed workout
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                lastCompletedWorkoutHistory.id,
                exerciseId
            )

            if (setHistories.isEmpty()) {
                return@withContext null
            }

            // Convert SetHistories to SimpleSet objects, matching ProgressionSection logic
            val executedSets = setHistories
                .filter { setHistory ->
                    // Filter out RestPauseSet sets
                    when(val setData = setHistory.setData){
                        is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                        is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                        is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                        else -> true
                    }
                }
                .mapNotNull { setHistory ->
                    when(val setData = setHistory.setData){
                        is WeightSetData -> {
                            val weight = setData.getWeight()
                            val reps = setData.actualReps
                            SimpleSet(weight, reps)
                        }
                        is BodyWeightSetData -> {
                            val weight = setData.getWeight()
                            val reps = setData.actualReps
                            SimpleSet(weight, reps)
                        }
                        else -> null
                    }
                }

            if (executedSets.isEmpty()) {
                return@withContext null
            }

            return@withContext executedSets
        }
    }

    private suspend fun preProcessExercises(){
        val exercises =
            selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        val validExercises = exercises.filter { exercise ->  !exercise.doNotStoreHistory && exercise.enableProgression }

        //this is setting the exercise to have either the sets from latest history of the ones from last successful session

        validExercises.forEach { exercise ->
            val sessionDecision = computeSessionDecision(exercise.id)

            val derivedSets = if (exercise.doNotStoreHistory) {
                exercise.sets
            } else {
                exercise.sets.map { set ->
                    if (latestSetHistoryMap.containsKey(set.id)) {
                        getNewSetFromSetHistory(latestSetHistoryMap[set.id]!!)
                    } else {
                        set
                    }
                }
            }

            val historySets = if (sessionDecision.shouldLoadLastSuccessfulSession) {
                sessionDecision.lastSuccessfulSession.map { getNewSetFromSetHistory(it) }
            } else {
                emptyList()
            }

            val setsToUse = if (sessionDecision.shouldLoadLastSuccessfulSession){
                historySets.ifEmpty { derivedSets }
            } else {
                derivedSets
            }

            val validSets = setsToUse
                .dropWhile { it is RestSet }
                .dropLastWhile { it is RestSet }

            updateWorkout(exercise,exercise.copy(sets = validSets))
        }

        lastSessionWorkout = _selectedWorkout.value.copy()
    }

    private fun applyProgressions() {
        val exercises =
            selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        val validExercises = exercises.filter { exercise -> 
            exercise.enabled && 
            exercise.enableProgression && 
            !exercise.doNotStoreHistory && 
            exerciseProgressionByExerciseId.containsKey(exercise.id)
        }

        validExercises.forEach { exercise ->
            val exerciseProgression = exerciseProgressionByExerciseId[exercise.id]!!.first

            val validSets = removeRestAndRestPause(
                sets = exercise.sets,
                isRestPause = {
                    when (it) {
                        is BodyWeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                        is WeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                        else -> false
                    }
                },
                isRestSet = { it is RestSet } // adapt if your rest set type differs
            )

            val distributedSets = exerciseProgression.sets
            val newSets = mutableListOf<Set>()

            val exerciseSets = validSets.filter { it !is RestSet }
            val restSets = validSets.filterIsInstance<RestSet>()

            for ((index, setInfo) in distributedSets.withIndex()) {
                if (index > 0) {
                    val previousRestSet = restSets.getOrNull(index - 1)

                    var newRestSet = RestSet(UUID.randomUUID(), 90)

                    if (previousRestSet != null) {
                        newRestSet = newRestSet.copy(id = previousRestSet.id,previousRestSet.timeInSeconds)
                    }

                    newSets.add(newRestSet)
                }

                val setId = exerciseSets.getOrNull(index)?.id ?: UUID.randomUUID()
                val newSet = when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)

                        val weight =  setInfo.weight - relativeBodyWeight

                        BodyWeightSet(setId, setInfo.reps, weight)
                    }

                    ExerciseType.WEIGHT -> {
                        WeightSet(setId, setInfo.reps, setInfo.weight)
                    }

                    else -> throw IllegalArgumentException("Unknown exercise type")
                }

                newSets.add(newSet)
            }

            val newExercise = exercise.copy(sets = newSets)
            updateWorkout(exercise, newExercise)
        }

        initializeExercisesMaps(selectedWorkout.value)
    }

    protected suspend fun generateProgressions() {
        exerciseProgressionByExerciseId.clear()
        plateauReasonByExerciseId.clear()

        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        val exercisesWithEquipments = exercises.filter { it.enabled && it.equipmentId != null }

        // Fix: Ensure weightsByEquipment is populated BEFORE calling processExercise
        // Use forEach instead of map to ensure eager evaluation
        exercisesWithEquipments.forEach { exercise ->
            val equipment =
                exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }

            if (equipment != null && !weightsByEquipment.containsKey(equipment)) {
                val possibleCombinations = equipment.getWeightsCombinations()
                weightsByEquipment[equipment] = possibleCombinations
            }
        }

        val validExercises = exercises.filter { it -> it.enabled && it.enableProgression && !it.doNotStoreHistory }
            .filter { it.exerciseType == ExerciseType.WEIGHT || it.exerciseType == ExerciseType.BODY_WEIGHT  }

        validExercises.forEach { exercise ->
            val result = processExercise(exercise)
            result?.let { (exerciseId, progression) ->
                exerciseProgressionByExerciseId[exerciseId] = progression
            }
        }
    }

    data class SessionDecision(
        val progressionState: ProgressionState,
        val shouldLoadLastSuccessfulSession: Boolean,
        val lastSuccessfulSession : List<SetHistory>
    )

    suspend fun computeSessionDecision(
        exerciseId: UUID,
    ): SessionDecision {
        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exerciseId)

        val fails = exerciseInfo?.sessionFailedCounter?.toInt() ?: 0
        val lastWasDeload = exerciseInfo?.lastSessionWasDeload ?: false

        val today = LocalDate.now()

        var weeklyCount = 0
        exerciseInfo?.weeklyCompletionUpdateDate?.let { lastUpdate ->
            val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                weeklyCount = exerciseInfo.timesCompletedInAWeek
            }
        }

        val shouldDeload = false // temporarily disable deload: (fails >= 2) && !lastWasDeload
        val shouldRetry = !lastWasDeload && (fails >= 1 || weeklyCount > 1)
        val shouldLoadLastSuccessfulSession = lastWasDeload || shouldRetry

        val progressionState = if(shouldDeload) ProgressionState.DELOAD else if(shouldRetry) ProgressionState.RETRY else ProgressionState.PROGRESS

        return SessionDecision(progressionState, shouldLoadLastSuccessfulSession,exerciseInfo?.lastSuccessfulSession ?: emptyList())
    }

    // Helper function to process a single exercise
    private suspend fun processExercise(
        exercise: Exercise,
    ): Pair<UUID, Pair<DoubleProgressionHelper.Plan, ProgressionState>> {
        val repsRange = IntRange(
                exercise.minReps,
                exercise.maxReps
            )

        val baseAvailableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> {
                // Fix: Ensure equipment weights are populated if missing
                val equipment = exercise.equipmentId?.let { getEquipmentById(it) }
                if (equipment != null && equipment is WeightLoadedEquipment && !weightsByEquipment.containsKey(equipment)) {
                    val possibleCombinations = equipment.getWeightsCombinations()
                    weightsByEquipment[equipment] = possibleCombinations
                }
                exercise.equipmentId?.let { getWeightByEquipment(getEquipmentById(it)) }
                    ?: emptySet()
            }

            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    getWeightByEquipment(getEquipmentById(it))
                        .map { value -> relativeBodyWeight + value }.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }

            else -> throw IllegalArgumentException("Unknown exercise type")
        }

        val sessionDecision = computeSessionDecision(exercise.id)

        // Check for plateau detection
        // Get all set histories for this exercise (across all workouts)
        val setHistories = setHistoryDao.getSetHistoriesByExerciseId(exercise.id)
        
        // Get all workout history IDs referenced by these set histories
        val workoutHistoryIds = setHistories
            .mapNotNull { it.workoutHistoryId }
            .toSet()
        
        // Get all workout histories that contain sets for this exercise (across all workouts)
        // This ensures we have complete data for plateau detection regardless of workout template
        val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()
            .filter { it.id in workoutHistoryIds && it.isDone }
            .associateBy { it.id }
        
        // Get progression states for all workout histories with this exercise
        val exerciseProgressions = exerciseSessionProgressionDao.getByExerciseId(exercise.id)
        val progressionStatesByWorkoutHistoryId = exerciseProgressions
            .filter { it.workoutHistoryId in workoutHistoryIds }
            .associate { it.workoutHistoryId to it.progressionState }
        
        // Get equipment for BIN_SIZE calculation
        val equipment = exercise.equipmentId?.let { getEquipmentById(it) }
        
        val (isPlateau, _, reason) = PlateauDetectionHelper.detectPlateauFromHistories(
            setHistories,
            workoutHistories,
            progressionStatesByWorkoutHistoryId,
            equipment
        )

        if (isPlateau) {
            Log.d("WorkoutViewModel", "${exercise.name}: Plateau detected")
        }

        // Store plateau detection result and reason for UI display
        plateauReasonByExerciseId[exercise.id] = if (isPlateau) reason else null

        val validSets = removeRestAndRestPause(
            sets = exercise.sets,
            isRestPause = {
                when (it) {
                    is BodyWeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                    is WeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                    else -> false
                }
            },
            isRestSet = { it is RestSet } // adapt if your rest set type differs
        ).filter { it !is RestSet }

        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exercise.id)


        val previousSets = validSets.map { set ->
            when (set) {
                is BodyWeightSet -> {
                    val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    val weight = set.getWeight(relativeBodyWeight)
                    SimpleSet(weight, set.reps)
                }

                is WeightSet -> {
                    SimpleSet(set.weight, set.reps)
                }

                else -> throw IllegalStateException("Unknown set type encountered after filtering.")
            }
        }

        val previousVolume = previousSets.sumOf { it.weight * it.reps }

        val availableWeights = baseAvailableWeights.toSet()

        val oldSets = previousSets.mapIndexed { index, set ->
            if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                val relativeBodyWeight =
                    bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                "${set.weight} kg x ${set.reps} (${relativeBodyWeight} kg + ${set.weight - relativeBodyWeight} kg)"
            } else {
                "${set.weight} kg x ${set.reps}"
            }
        }

        if(exercise.exerciseType == ExerciseType.BODY_WEIGHT){
            val relativeBodyWeight =
                bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)

            Log.d(
                "WorkoutViewModel",
                "${exercise.name} (${exercise.exerciseType}) Relative BodyWeight: $relativeBodyWeight"
            )

        }else{
            Log.d(
                "WorkoutViewModel",
                "${exercise.name} (${exercise.exerciseType})"
            )
        }

        Log.d("WorkoutViewModel", "Old sets: ${oldSets.joinToString(", ")}")

        val exerciseProgression = when {
            // Always respect deload decision
            sessionDecision.progressionState ==  ProgressionState.DELOAD -> {
                Log.d("WorkoutViewModel", "Deload")

                DoubleProgressionHelper.planDeloadSession(
                    previousSets = previousSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange
                )
            }
            sessionDecision.progressionState == ProgressionState.RETRY -> {
                Log.d("WorkoutViewModel", "Retrying")
                DoubleProgressionHelper.Plan(
                    previousSets,
                    previousVolume,
                    previousVolume
                )
            }

            sessionDecision.progressionState == ProgressionState.PROGRESS -> {
                val jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(
                    defaultPct = exercise.loadJumpDefaultPct ?: 0.025,
                    maxPct = exercise.loadJumpMaxPct ?: 0.5,
                    overcapUntil = exercise.loadJumpOvercapUntil ?: 2
                )
                DoubleProgressionHelper.planNextSession(
                    previousSets = previousSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange,
                    jumpPolicy = jumpPolicy
                )
            }
            else -> {
                throw IllegalStateException("Unknown progression state")
            }
        }

        val newSets = exerciseProgression.sets.mapIndexed { index, set ->
            if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                val relativeBodyWeight =
                    bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                "${set.weight} kg x ${set.reps} (${relativeBodyWeight} kg + ${set.weight - relativeBodyWeight} kg)"
            } else {
                "${set.weight} kg x ${set.reps}"
            }
        }

        Log.d("WorkoutViewModel", "New sets: ${newSets.joinToString(", ")}")

        val progressIncrease = ((exerciseProgression.newVolume - exerciseProgression.previousVolume) / exerciseProgression.previousVolume) * 100

        Log.d(
            "WorkoutViewModel",
            "Volume: ${exerciseProgression.previousVolume.round(2)} -> ${exerciseProgression.newVolume .round(2)} (${if(progressIncrease>0) "+" else ""}${progressIncrease.round(2)}%)")

        val couldNotFindProgression = sessionDecision.progressionState == ProgressionState.PROGRESS &&
                exerciseProgression.previousVolume.round(2) == exerciseProgression.newVolume.round(2)

        val progressionState = when {
            couldNotFindProgression -> ProgressionState.FAILED
            else -> sessionDecision.progressionState
        }

        return exercise.id to (exerciseProgression to progressionState)
    }

    fun resumeLastState() {
        if (_workoutRecord == null) return

        fun isTargetResumeState(state: WorkoutState?): Boolean {
            return state is WorkoutState.Set &&
                    state.exerciseId == _workoutRecord!!.exerciseId &&
                    state.setIndex == _workoutRecord!!.setIndex
        }

        fun restoreTimerForTimeSet(state: WorkoutState.Set) {
            val set = state.set

            // Check if this is a time set
            val isTimeSet = set is TimedDurationSet || set is EnduranceSet
            if (!isTimeSet) return
            
            // Find the set history from executedSetsHistory (immutable snapshot from StateFlow)
            val setHistory = executedSetStore.executedSets.value.firstOrNull { 
                it.setId == set.id && it.order == state.setIndex 
            }
            
            if (setHistory == null) return
            
            val setData = setHistory.setData
            val now = LocalDateTime.now()
            
            when {
                set is TimedDurationSet && setData is TimedDurationSetData -> {
                    // Only restore if timer was running (endTimer < startTimer and endTimer > 0)
                    // This excludes cases where timer finished (endTimer = 0) or never started (endTimer = startTimer)
                    if (setData.endTimer < setData.startTimer && setData.endTimer > 0) {
                        // Calculate elapsed time: startTimer - endTimer
                        val elapsedMillis = setData.startTimer - setData.endTimer
                        // Restore startTime so that elapsed time matches
                        state.startTime = now.minusNanos((elapsedMillis * 1_000_000L).toLong())
                    }
                }
                set is EnduranceSet && setData is EnduranceSetData -> {
                    // Only restore if timer was running (endTimer > 0)
                    if (setData.endTimer > 0) {
                        // Restore startTime so that elapsed time matches endTimer
                        state.startTime = now.minusNanos((setData.endTimer * 1_000_000L).toLong())
                    }
                }
            }
        }

        // When we land on Preparing before resuming, the state machine already knows the real state.
        // Sync the UI-facing state so comparisons run against the latest value.
        if (_workoutState.value is WorkoutState.Preparing && stateMachine != null) {
            updateStateFlowsFromMachine()
        }

        val currentState = _workoutState.value
        if (isTargetResumeState(currentState) && currentState is WorkoutState.Set) {
            restoreTimerForTimeSet(currentState)
            return
        }

        viewModelScope.launch(dispatchers.io) {
            _isResuming.value = true
            while (true) {
                val machineState = stateMachine?.currentState ?: break
                if (machineState is WorkoutState.Completed) {
                    break
                }

                if (isTargetResumeState(machineState) && machineState is WorkoutState.Set) {
                    restoreTimerForTimeSet(machineState)
                    //go to the next set after the target set which is not rest
                    do{
                        goToNextState()
                    } while (_workoutState.value is WorkoutState.Rest)
                    break
                }

                goToNextState()
            }

            delay(2000)
            _isResuming.value = false
            rebuildScreenState()
        }
    }

    open fun startWorkout() {
        viewModelScope.launch(dispatchers.main) {
            withContext(dispatchers.io) {
                try {
                    _enableWorkoutNotificationFlow.value = null
                    _currentScreenDimmingState.value = false

                    val preparingState = WorkoutState.Preparing(dataLoaded = false)
                    _workoutState.value = preparingState

                    stateMachine = null
                    setStates.clear()
                    allWorkoutStates.clear()
                    weightsByEquipment.clear()
                    executedSetStore.clear()
                    heartBeatHistory.clear()
                    startWorkoutTime = null
                    currentWorkoutHistory = null
                    _isPaused.value = false

                    val selectedWorkoutId = _selectedWorkoutId.value
                    val foundWorkout = _workouts.value.find { it.id == selectedWorkoutId }
                    
                    if (foundWorkout == null) {
                        Log.e("WorkoutViewModel", "Workout not found for id: $selectedWorkoutId")
                        _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
                        return@withContext
                    }
                    
                    _selectedWorkout.value = foundWorkout
                    rebuildScreenState()

                    loadWorkoutHistory()

                    preProcessExercises()
                    generateProgressions()
                    applyProgressions()
                    val workoutStates = generateWorkoutStates()

                    // Populate allWorkoutStates and setStates for other APIs
                    workoutStates.forEachIndexed { index, it ->
                        if (index == workoutStates.lastIndex && it is WorkoutState.Rest) {
                            return@forEachIndexed
                        }
                        allWorkoutStates.add(it)
                        if(it is WorkoutState.Set){
                            setStates.addLast(it)
                        }
                    }

                    // Initialize state machine (without Completed state - will be added in setWorkoutStart())
                    stateMachine = initializeStateMachine(allWorkoutStates)
                    updateStateFlowsFromMachine()
                    _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
                    triggerWorkoutNotification()
                } catch (e: Exception) {
                    Log.e("WorkoutViewModel", "Error in startWorkout()", e)
                    val currentState = _workoutState.value
                    if (currentState is WorkoutState.Preparing) {
                        _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
                    }
                    throw e
                }
            }
        }
    }

    protected suspend fun restoreExecutedSets() {
        if (_workoutRecord == null) return;
        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        // Collect all set histories first
        val allSetHistories = mutableListOf<SetHistory>()
        exercises.filter { !it.doNotStoreHistory }.forEach { exercise ->
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                _workoutRecord!!.workoutHistoryId,
                exercise.id
            )
            allSetHistories.addAll(setHistories)
        }

        // Replace all executed sets atomically via store
        executedSetStore.replaceAll(allSetHistories)
    }

    protected suspend fun loadWorkoutHistory() {
        val workoutHistories = workoutHistoryDao
            .getAllWorkoutHistories()
            .filter { it.globalId == selectedWorkout.value.globalId && it.isDone }
            .sortedWith(compareByDescending<WorkoutHistory> { it.date }.thenByDescending { it.time })

        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        val calledIndexes = mutableListOf<Int>()

        exercises.filter { !it.doNotStoreHistory }.forEach { exercise ->
            var workoutHistoryIndex = 0;
            val setHistoriesFound = mutableListOf<SetHistory>()
            while (workoutHistoryIndex < workoutHistories.size) {
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                    workoutHistories[workoutHistoryIndex].id,
                    exercise.id
                )
                setHistoriesFound.clear()
                setHistoriesFound.addAll(setHistories)

                if (setHistories.isNotEmpty()) {
                    if (!calledIndexes.contains(workoutHistoryIndex)) {
                        calledIndexes.add(workoutHistoryIndex)
                    }

                    break
                } else {
                    workoutHistoryIndex++
                }
            }

            for (setHistoryFound in setHistoriesFound) {
                latestSetHistoryMap[setHistoryFound.setId] = setHistoryFound
            }

            latestSetHistoriesByExerciseId[exercise.id] =
                setHistoriesFound.distinctBy { it.setId }.toList()
        }

        /*
        val neverCalledWorkoutHistories =
            workoutHistories.filterIndexed { index, _ -> index !in calledIndexes }

        neverCalledWorkoutHistories.forEach {
            workoutHistoryDao.deleteById(it.id)
        }
        */
    }

    open fun registerHeartBeat(heartBeat: Int) {
        heartBeatHistory.add(heartBeat)
    }

    private fun updateWorkout(currentExercise: Exercise, updatedExercise: Exercise) {
        val updatedComponents = updateWorkoutComponentsRecursively(
            _selectedWorkout.value.workoutComponents,
            currentExercise,
            updatedExercise
        )
        _selectedWorkout.value = _selectedWorkout.value.copy(workoutComponents = updatedComponents)
        rebuildScreenState()
    }

    fun addNewSetStandard() {
        if (_workoutState.value !is WorkoutState.Set) return
        val currentState = _workoutState.value as WorkoutState.Set

        val currentSetIndex =
            exercisesById[currentState.exerciseId]!!.sets.indexOf(currentState.set)
        val currentExercise = exercisesById[currentState.exerciseId]!!

        val newSets = currentExercise.sets.toMutableList()
        val newRestSet = RestSet(UUID.randomUUID(), 90)
        newSets.add(currentSetIndex + 1, newRestSet)
        val newSet = getNewSet(currentState.set)
        newSets.add(currentSetIndex + 2, newSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise, updatedExercise)

        RefreshAndGoToNextState()
    }

    fun addNewRest() {
        if (_workoutState.value !is WorkoutState.Set) return
        val currentState = _workoutState.value as WorkoutState.Set

        val currentSetIndex =
            exercisesById[currentState.exerciseId]!!.sets.indexOf(currentState.set)
        val currentExercise = exercisesById[currentState.exerciseId]!!

        val newSets = currentExercise.sets.toMutableList()
        val newRestSet = RestSet(UUID.randomUUID(), 90)
        newSets.add(currentSetIndex + 1, newRestSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise, updatedExercise)

        RefreshAndGoToNextState()
    }

    fun addNewRestPauseSet() {
        if (_workoutState.value !is WorkoutState.Set) return
        val currentState = _workoutState.value as WorkoutState.Set
        if (currentState.set !is BodyWeightSet && currentState.set !is WeightSet) return

        val currentSetIndex =
            exercisesById[currentState.exerciseId]!!.sets.indexOf(currentState.set)
        val currentExercise = exercisesById[currentState.exerciseId]!!

        val newSets = currentExercise.sets.toMutableList()
        val newRestSet = RestSet(UUID.randomUUID(), 30, SetSubCategory.RestPauseSet)

        newSets.add(currentSetIndex + 1, newRestSet)
        val newSet = when (val new = getNewSet(currentState.set)) {
            is BodyWeightSet -> new.copy(reps = 3, subCategory = SetSubCategory.RestPauseSet)
            is WeightSet -> new.copy(reps = 3, subCategory = SetSubCategory.RestPauseSet)
            else -> throw IllegalArgumentException("Unknown set type")
        }
        newSets.add(currentSetIndex + 2, newSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise, updatedExercise)

        RefreshAndGoToNextState()
    }

    protected fun RefreshAndGoToNextState() {
        viewModelScope.launch(dispatchers.io) {
            if (_isRefreshing.value || (_workoutState.value !is WorkoutState.Set && _workoutState.value !is WorkoutState.Rest)) return@launch

            _isRefreshing.value = true

            val targetSetId = when (_workoutState.value) {
                is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                else -> throw RuntimeException("Invalid state")
            }

            // Count how many states with this setId were in history before refresh
            val oldHistory = stateMachine?.history ?: emptyList()
            val completedMatchingCount = oldHistory.count { state ->
                val setId = when (state) {
                    is WorkoutState.Set -> state.set.id
                    is WorkoutState.Rest -> state.set.id
                    else -> null
                }
                setId == targetSetId
            }

            setStates.clear()
            allWorkoutStates.clear()

            val workoutStates = generateWorkoutStates()

            workoutStates.forEachIndexed { index, it ->
                if (index == workoutStates.lastIndex && it is WorkoutState.Rest) {
                    return@forEachIndexed
                }
                allWorkoutStates.add(it)
                if(it is WorkoutState.Set){
                    setStates.addLast(it)
                }
            }

            // Initialize new state machine starting at the beginning
            var newMachine = initializeStateMachine(allWorkoutStates)
            
            // Find the (completedMatchingCount + 1)th occurrence of targetSetId
            // This corresponds to the state we were at before refresh
            var occurrenceCount = 0
            var targetIndex = -1
            
            for (i in 0 until newMachine.allStates.size) {
                val state = newMachine.allStates[i]
                val setId = when (state) {
                    is WorkoutState.Set -> state.set.id
                    is WorkoutState.Rest -> state.set.id
                    else -> null
                }
                if (setId == targetSetId) {
                    occurrenceCount++
                    if (occurrenceCount == completedMatchingCount + 1) {
                        targetIndex = i
                        break
                    }
                }
            }
            
            // If we found the target, reposition and advance one step
            if (targetIndex >= 0) {
                // Create a machine positioned at the target index
                newMachine = WorkoutStateMachine(newMachine.allStates, targetIndex) { LocalDateTime.now() }
                // Advance one step to get to the next state after the target
                if (!newMachine.isCompleted) {
                    newMachine = newMachine.next()
                }
            }
            
            stateMachine = newMachine
            updateStateFlowsFromMachine()

            _isRefreshing.value = false
            rebuildScreenState()
        }
    }

    /**
     * Gets the last session from history for an exercise, excluding the current workout history.
     * This is used for comparison purposes (vsPrevious), not for retry logic.
     * 
     * @param exerciseId The exercise ID to get history for
     * @param excludeWorkoutHistoryId The workout history ID to exclude (typically the current session being saved)
     * @return List of SetHistory representing the last session, or empty list if none found
     */
    private suspend fun getLastSessionFromHistory(
        exerciseId: UUID,
        excludeWorkoutHistoryId: UUID?
    ): List<SetHistory> {
        // Query all workout histories for the current workout, ordered by date DESC
        val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()
            .filter { 
                it.globalId == selectedWorkout.value.globalId && 
                it.isDone && 
                it.id != excludeWorkoutHistoryId
            }
            .sortedWith(Comparator { a, b ->
                val dateCompare = b.date.compareTo(a.date)
                if (dateCompare != 0) dateCompare else b.time.compareTo(a.time)
            })

        // Find the first workout history that has set histories for this exercise
        for (workoutHistory in workoutHistories) {
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                workoutHistory.id,
                exerciseId
            )
            
            if (setHistories.isNotEmpty()) {
                // Process and filter sets the same way as currentSession
                val processedSession = setHistories
                    .dropWhile { it.setData is RestSetData }
                    .dropLastWhile { it.setData is RestSetData }
                    .filter {
                        when (val sd = it.setData) {
                            is BodyWeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet
                            is WeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet
                            is RestSetData -> sd.subCategory != SetSubCategory.RestPauseSet
                            else -> true
                        }
                    }
                
                // Return if we have any sets after processing
                if (processedSession.isNotEmpty()) {
                    return processedSession
                }
            }
        }
        
        return emptyList()
    }

    open fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context? = null,
        forceNotSend: Boolean = false,
        onEnd: suspend () -> Unit = {}
    ) {
        viewModelScope.launch(dispatchers.io) {
            storeSetDataJob?.join()
            val duration = Duration.between(startWorkoutTime!!, LocalDateTime.now())

            if (currentWorkoutHistory == null) {
                currentWorkoutHistory = WorkoutHistory(
                    id = UUID.randomUUID(),
                    workoutId = selectedWorkout.value.id,
                    date = LocalDate.now(),
                    duration = duration.seconds.toInt(),
                    heartBeatRecords = heartBeatHistory.toList(),
                    time = LocalTime.now(),
                    startTime = startWorkoutTime!!,
                    isDone = isDone,
                    hasBeenSentToHealth = false,
                    globalId = selectedWorkout.value.globalId
                )
            } else {
                currentWorkoutHistory = currentWorkoutHistory!!.copy(
                    duration = duration.seconds.toInt(),
                    heartBeatRecords = heartBeatHistory.toList(),
                    time = LocalTime.now(),
                    isDone = isDone,
                    hasBeenSentToHealth = false,
                    version = currentWorkoutHistory!!.version.inc()
                )
            }

            // Take a snapshot of executedSetsHistory (immutable from StateFlow)
            val executedSetsHistorySnapshot = executedSetStore.executedSets.value

            val newExecutedSetsHistory = executedSetsHistorySnapshot.map {
                it.copy(workoutHistoryId = currentWorkoutHistory!!.id)
            }
            
            // Replace all executed sets atomically via store
            executedSetStore.replaceAll(newExecutedSetsHistory)

            workoutHistoryDao.insertWithVersionCheck(currentWorkoutHistory!!)
            setHistoryDao.insertAllWithVersionCheck(*newExecutedSetsHistory.toTypedArray())

            if (isDone) {
                // Use the snapshot for grouping to avoid concurrent modification
                val executedSetsHistoryByExerciseId = newExecutedSetsHistory.groupBy { it.exerciseId }
                val exercises = _selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + _selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

                executedSetsHistoryByExerciseId.forEach { it ->
                    val exercise = exercises.firstOrNull { item -> item.id == it.key }

                    if(exercise == null){
                        Log.e("WorkoutViewModel", "Exercise with id ${it.key} not found")
                        return@forEach
                    }

                    val isTrackableExercise = !exercise.doNotStoreHistory &&
                            (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
                    if(!isTrackableExercise) return@forEach

                    val progressionData =
                        if (exerciseProgressionByExerciseId.containsKey(it.key)) exerciseProgressionByExerciseId[it.key] else null

                    val exerciseProgression = progressionData?.first
                    val progressionState = progressionData?.second

                    val isDeloadSession = progressionState == ProgressionState.DELOAD

                    val exerciseHistories = it.value

                    val currentSession = exerciseHistories
                        .dropWhile { it.setData is RestSetData }
                        .dropLastWhile { it.setData is RestSetData }
                        .filter {
                            when (val sd = it.setData) {
                                is BodyWeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet
                                is WeightSetData     -> sd.subCategory != SetSubCategory.RestPauseSet
                                is RestSetData       -> sd.subCategory != SetSubCategory.RestPauseSet
                                else -> true
                            }
                        }

                    val exerciseInfo = exerciseInfoDao.getExerciseInfoById(it.key!!)

                    val today = LocalDate.now()

                    var weeklyCount = 0
                    if (exerciseInfo != null) {
                        val lastUpdate = exerciseInfo.weeklyCompletionUpdateDate
                        if (lastUpdate != null) {
                            val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                            val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                            if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                                weeklyCount = exerciseInfo.timesCompletedInAWeek
                            }
                        }
                    }
                    weeklyCount++

                    val executedSets = currentSession.mapNotNull { setHistory ->
                        when (val setData = setHistory.setData) {
                            is WeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            is BodyWeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            else -> null
                        }
                    }

                    val expectedSets = exerciseProgression?.sets ?: emptyList()
                    val vsExpected = if (exerciseProgression != null) {
                        compareSetListsUnordered(executedSets, expectedSets)
                    } else {
                        Ternary.EQUAL
                    }

                    // Get last session from history for comparison (not retry logic)
                    val lastSessionFromHistory = getLastSessionFromHistory(it.key!!, currentWorkoutHistory!!.id)
                    val previousSessionSets = if (lastSessionFromHistory.isNotEmpty()) {
                        lastSessionFromHistory.mapNotNull { setHistory ->
                            when (val setData = setHistory.setData) {
                                is WeightSetData -> {
                                    if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                    SimpleSet(setData.getWeight(), setData.actualReps)
                                }
                                is BodyWeightSetData -> {
                                    if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                    SimpleSet(setData.getWeight(), setData.actualReps)
                                }
                                else -> null
                            }
                        }
                    } else {
                        emptyList()
                    }

                    val vsPrevious = if (previousSessionSets.isNotEmpty()) {
                        compareSetListsUnordered(executedSets, previousSessionSets)
                    } else {
                        Ternary.EQUAL
                    }

                    val previousSessionVolume = previousSessionSets.sumOf { it.weight * it.reps }
                    val expectedVolume = expectedSets.sumOf { it.weight * it.reps }
                    val executedVolume = executedSets.sumOf { it.weight * it.reps }

                    if (exerciseInfo == null) {
                        val newExerciseInfo = ExerciseInfo(
                            id = it.key!!,
                            bestSession = currentSession,
                            lastSuccessfulSession = currentSession,
                            successfulSessionCounter = 1u,
                            sessionFailedCounter = 0u,
                            timesCompletedInAWeek = weeklyCount,
                            weeklyCompletionUpdateDate = today,
                            lastSessionWasDeload = false,
                        )
                        exerciseInfoDao.insert(newExerciseInfo)
                    } else {
                        var updatedInfo = exerciseInfo.copy(version = exerciseInfo.version + 1u)

                        if (isDeloadSession) {
                            updatedInfo = updatedInfo.copy(
                                sessionFailedCounter = 0u,
                                successfulSessionCounter = 0u,
                                lastSessionWasDeload = true
                            )
                        } else {
                            updatedInfo = updatedInfo.copy(lastSessionWasDeload = false)

                            // Convert best session to SimpleSet list for comparison
                            val bestSessionSets = updatedInfo.bestSession.mapNotNull { setHistory ->
                                when (val setData = setHistory.setData) {
                                    is WeightSetData -> {
                                        if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                        SimpleSet(setData.getWeight(), setData.actualReps)
                                    }
                                    is BodyWeightSetData -> {
                                        if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                        SimpleSet(setData.getWeight(), setData.actualReps)
                                    }
                                    else -> null
                                }
                            }

                            // Check if current session is better than best session
                            val vsBest = compareSetListsUnordered(executedSets, bestSessionSets)
                            if (vsBest == Ternary.ABOVE) {
                                updatedInfo = updatedInfo.copy(bestSession = currentSession)
                            }

                            if (progressionState != null) {
                                when (progressionState) {
                                    ProgressionState.PROGRESS -> {
                                        // Success if executed sets are ABOVE or EQUAL to expected sets
                                        // Failure if exerciseProgression is null, expectedSets is empty, or vsExpected is BELOW/MIXED
                                        val isSuccess = exerciseProgression != null && 
                                            expectedSets.isNotEmpty() &&
                                            (vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL)

                                        updatedInfo = if (isSuccess) {
                                            updatedInfo.copy(
                                                lastSuccessfulSession = currentSession,
                                                successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                                sessionFailedCounter = 0u
                                            )
                                        } else {
                                            // PROGRESS failure: reset successfulSessionCounter to 0
                                            updatedInfo.copy(
                                                successfulSessionCounter = 0u,
                                                sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                            )
                                        }
                                    }
                                    ProgressionState.RETRY -> {
                                        // ProgressionState.RETRY (DELOAD was already handled above)
                                        when (vsExpected) {
                                            Ternary.ABOVE -> {
                                                // Exceeded retry target - success
                                                updatedInfo = updatedInfo.copy(
                                                    lastSuccessfulSession = currentSession,
                                                    successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                                    sessionFailedCounter = 0u
                                                )
                                            }
                                            Ternary.EQUAL -> {
                                                // Met retry target exactly - complete retry, reset counters
                                                updatedInfo = updatedInfo.copy(
                                                    lastSuccessfulSession = currentSession,
                                                    successfulSessionCounter = 0u,
                                                    sessionFailedCounter = 0u
                                                )
                                            }
                                            Ternary.BELOW, Ternary.MIXED -> {
                                                // Below retry target - session failed, don't update counters
                                                // Counters remain unchanged (will be incremented elsewhere if needed)
                                            }
                                        }
                                    }
                                    ProgressionState.FAILED -> {
                                        // FAILED state: progression could not be calculated (e.g., same volume)
                                        // Treat as failure
                                        updatedInfo = updatedInfo.copy(
                                            successfulSessionCounter = 0u,
                                            sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                        )
                                    }
                                    ProgressionState.DELOAD -> {
                                        // DELOAD is handled earlier, but this case should not happen here
                                        // Leave counters as-is (already handled above)
                                    }
                                }
                            } else {
                                // No progression state - compare against last successful session
                                // However, if we have exerciseProgression but progressionState is null,
                                // we should still check vsExpected to handle PROGRESS successes/failures correctly
                                if (exerciseProgression != null && expectedSets.isNotEmpty()) {
                                    if (vsExpected == Ternary.BELOW || vsExpected == Ternary.MIXED) {
                                        // This is a PROGRESS failure even though progressionState is null
                                        // Reset successfulSessionCounter to 0
                                        updatedInfo = updatedInfo.copy(
                                            successfulSessionCounter = 0u,
                                            sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                        )
                                    } else if (vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL) {
                                        // This is a PROGRESS success even though progressionState is null
                                        // Increment successfulSessionCounter
                                        updatedInfo = updatedInfo.copy(
                                            lastSuccessfulSession = currentSession,
                                            successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                            sessionFailedCounter = 0u
                                        )
                                    }
                                } else {
                                    val lastSessionSets = updatedInfo.lastSuccessfulSession.mapNotNull { setHistory ->
                                        when (val setData = setHistory.setData) {
                                            is WeightSetData -> {
                                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                                SimpleSet(setData.getWeight(), setData.actualReps)
                                            }
                                            is BodyWeightSetData -> {
                                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                                SimpleSet(setData.getWeight(), setData.actualReps)
                                            }
                                            else -> null
                                        }
                                    }

                                    val vsLast = compareSetListsUnordered(executedSets, lastSessionSets)

                                    updatedInfo = when (vsLast) {
                                        Ternary.ABOVE -> {
                                            // Exceeded last successful session - success
                                            updatedInfo.copy(
                                                lastSuccessfulSession = currentSession,
                                                successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                                sessionFailedCounter = 0u
                                            )
                                        }
                                        Ternary.EQUAL -> {
                                            // Equal to last successful session - no progress, reset counter
                                            updatedInfo.copy(
                                                lastSuccessfulSession = currentSession,
                                                successfulSessionCounter = 0u,
                                                sessionFailedCounter = 0u
                                            )
                                        }
                                        Ternary.BELOW, Ternary.MIXED -> {
                                            // Below last successful session - failure
                                            updatedInfo.copy(
                                                successfulSessionCounter = 0u,
                                                sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                            )
                                        }
                                    }
                                }
                            }
                        }

                        updatedInfo = updatedInfo.copy(
                            timesCompletedInAWeek = weeklyCount,
                            weeklyCompletionUpdateDate = today
                        )

                        exerciseInfoDao.insert(updatedInfo)
                    }

                    if (progressionData != null && progressionState != null) {
                        val progressionEntry = ExerciseSessionProgression(
                            id = UUID.randomUUID(),
                            workoutHistoryId = currentWorkoutHistory!!.id,
                            exerciseId = it.key!!,
                            expectedSets = expectedSets,
                            progressionState = progressionState,
                            vsExpected = vsExpected,
                            vsPrevious = vsPrevious,
                            previousSessionVolume = previousSessionVolume,
                            expectedVolume = expectedVolume,
                            executedVolume = executedVolume
                        )

                        exerciseSessionProgressionDao.insert(progressionEntry)
                    }
                }

                // Use newExecutedSetsHistory (already updated in executedSetsHistory) to avoid concurrent modification
                val setHistoriesByExerciseId = newExecutedSetsHistory
                    .filter { it.exerciseId != null }
                    .groupBy { it.exerciseId }

                var workoutComponents = _selectedWorkout.value.workoutComponents

                for (exercise in exercises) {
                    if(exercise.doNotStoreHistory) continue
                    val setHistories = setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order } ?: continue

                    workoutComponents = removeSetsFromExerciseRecursively(workoutComponents,exercise)

                    val validSetHistories = setHistories
                        .dropWhile { it.setData is RestSetData }
                        .dropLastWhile { it.setData is RestSetData }
                        .filter { it ->
                        when(val setData = it.setData){
                            is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            else -> true
                        }
                    }

                    for (setHistory in validSetHistories) {
                        val newSet = getNewSetFromSetHistory(setHistory)
                        workoutComponents = addSetToExerciseRecursively(workoutComponents,exercise,newSet,setHistory.order)
                    }
                }

                val currentWorkoutStore = workoutStoreRepository.getWorkoutStore()
                val newWorkoutStore =
                    currentWorkoutStore.copy(workouts = currentWorkoutStore.workouts.map {
                        if (it.id == _selectedWorkout.value.id) {
                            it.copy(workoutComponents = workoutComponents)
                        } else {
                            it
                        }
                    })

                updateWorkoutStore(newWorkoutStore)
                workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
            }

            onEnd()
        }
    }

    fun storeSetData() {
        val previousJob = storeSetDataJob
        val newJob = viewModelScope.launch(dispatchers.io) {
            previousJob?.join()
            storeSetDataInternal()
        }
        storeSetDataJob = newJob
        newJob.invokeOnCompletion {
            if (storeSetDataJob === newJob) {
                storeSetDataJob = null
            }
        }
    }

    private suspend fun storeSetDataInternal() {
        val currentState = _workoutState.value
        val currentSet = when (currentState) {
            is WorkoutState.Set -> currentState.set
            is WorkoutState.Rest -> currentState.set
            else -> return
        }

        if (currentSet is RestSet) return

        if (currentState is WorkoutState.Set) {
            val exercise = exercisesById[currentState.exerciseId]!!
            val isWarmupSet = when(val set = currentState.set) {
                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                else -> false
            }
            if (exercise.doNotStoreHistory || isWarmupSet) return
        }

        if(currentState is WorkoutState.Rest && currentState.isIntraSetRest) return

        val newSetHistory = when (currentState) {
            is WorkoutState.Set -> {
                // Use current time as fallback if startTime is null
                val startTime = currentState.startTime ?: LocalDateTime.now()
                SetHistory(
                    id = UUID.randomUUID(),
                    setId = currentState.set.id,
                    setData = currentState.currentSetData,
                    order = currentState.setIndex,
                    skipped = currentState.skipped,
                    exerciseId = currentState.exerciseId,
                    startTime = startTime,
                    endTime = LocalDateTime.now()
                )
            }

            is WorkoutState.Rest -> {
                // Use current time as fallback if startTime is null
                val startTime = currentState.startTime ?: LocalDateTime.now()
                SetHistory(
                    id = UUID.randomUUID(),
                    setId = currentState.set.id,
                    setData = currentState.currentSetData,
                    order = currentState.order,
                    skipped = false,
                    exerciseId = currentState.exerciseId,
                    startTime = startTime,
                    endTime = LocalDateTime.now()
                )
            }

            else -> return
        }

        // Upsert the set history entry atomically via store
        val key: (SetHistory) -> Boolean = when (currentState) {
            is WorkoutState.Set -> { history -> history.setId == currentState.set.id && history.order == currentState.setIndex }
            is WorkoutState.Rest -> { history -> history.setId == currentState.set.id && history.order == currentState.order }
            else -> return
        }
        executedSetStore.upsert(newSetHistory, key)
    }

    inline fun <reified T : SetData> getExecutedSetsDataByExerciseIdAndTakePriorToSetId(
        exerciseId: UUID,
        setId: UUID
    ): List<T> {
        // Take a snapshot (immutable from StateFlow)
        val snapshot = executedSetsHistory
        return snapshot
            .filter { it.exerciseId == exerciseId }
            .takeWhile { it.setId != setId }
            .mapNotNull { it.setData as? T }
    }

    inline fun <reified T : SetData> getHistoricalSetsDataByExerciseId(exerciseId: UUID): List<T> {
        if (exercisesById[exerciseId]!!.doNotStoreHistory || !latestSetHistoriesByExerciseId.containsKey(
                exerciseId
            )
        ) return emptyList()
        return latestSetHistoriesByExerciseId[exerciseId]!!.filter { it.setData is T }
            .map { it.setData as T }
    }

    protected suspend fun generateWorkoutStates() : List<WorkoutState> {
        val workoutComponents = selectedWorkout.value.workoutComponents.filter { it.enabled }
        val totalStates = mutableListOf<WorkoutState>()

        for ((index, workoutComponent) in workoutComponents.withIndex()) {
            when (workoutComponent) {
                is Exercise -> {
                    val states = addStatesFromExercise(workoutComponent)
                    totalStates.addAll(states)
                }
                is Rest -> {
                    val restSet = RestSet(workoutComponent.id, workoutComponent.timeInSeconds)

                    val restState = WorkoutState.Rest(
                        set = restSet,
                        order = index.toUInt(),
                        currentSetDataState = mutableStateOf(initializeSetData(
                            RestSet(
                                workoutComponent.id,
                                workoutComponent.timeInSeconds
                            )
                        ))
                    )

                    totalStates.add(restState)
                }

                is Superset -> {
                    val superset = workoutComponent
                    val queues = superset.exercises.map { ex -> mutableListOf(*addStatesFromExercise(ex).toTypedArray()) }
                    val out = mutableListOf<WorkoutState>()

                    // 1) Alternate WARM-UPS across exercises (keep their intrinsic rest)
                    var anyWarmups = true
                    while (anyWarmups) {
                        anyWarmups = false
                        for (q in queues) {
                            if (q.isEmpty() || q.first() !is WorkoutState.Set) continue
                            val s = q.first() as WorkoutState.Set
                            val isWarmupSet = when(val set = s.set) {
                                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                else -> false
                            }
                            if (!isWarmupSet) continue
                            anyWarmups = true
                            out.add(q.removeAt(0) as WorkoutState.Set)
                            if (q.isNotEmpty() && q.first() is WorkoutState.Rest) {
                                val r = q.first() as WorkoutState.Rest
                                q.removeAt(0) //if (r.exerciseId == s.exerciseId) out.add(q.removeAt(0))
                            }
                        }
                    }

                    // Strip any leading rest before work phase
                    for (q in queues) while (q.isNotEmpty() && q.first() is WorkoutState.Rest) q.removeAt(0)

                    fun workCount(q: MutableList<WorkoutState>) =
                        q.count { 
                            if (it !is WorkoutState.Set) false
                            else {
                                val isWarmupSet = when(val set = it.set) {
                                    is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                    is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                    else -> false
                                }
                                !isWarmupSet
                            }
                        }
                    val rounds = queues.minOfOrNull { workCount(it) } ?: 0

                    // 2) Alternate WORK sets; rest comes from superset.restSecondsByExercise
                    for (round in 0 until rounds) {
                        for (q in queues) {
                            while (q.isNotEmpty() && q.first() !is WorkoutState.Set) q.removeAt(0)
                            if (q.isEmpty()) continue
                            val s = q.first() as WorkoutState.Set
                            if (s.isWarmupSet) { q.removeAt(0); continue } // safety, should be none now

                            out.add(q.removeAt(0) as WorkoutState.Set)

                            val restSec = superset.restSecondsByExercise[s.exerciseId] ?: 0
                            if (restSec > 0) {
                                val restSet = RestSet(UUID.randomUUID(), restSec)
                                out.add(
                                    WorkoutState.Rest(
                                        set = restSet,
                                        order = (round + 1).toUInt(),
                                        currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                                        exerciseId = s.exerciseId
                                    )
                                )
                            }

                            // Drop intrinsic rest after work sets to avoid double-rest
                            while (q.isNotEmpty() && q.first() is WorkoutState.Rest) q.removeAt(0)
                        }
                    }

                    // 3) Tail: append any leftover sets (skip leftover rests)
//                    while (queues.any { it.isNotEmpty() }) {
//                        for (q in queues) {
//                            while (q.isNotEmpty() && q.first() !is WorkoutState.Set) q.removeAt(0)
//                            if (q.isNotEmpty()) out.add(q.removeAt(0) as WorkoutState.Set)
//                        }
//                    }

                    val cleaned = mutableListOf<WorkoutState>()
                    for (st in out) {
                        if (st is WorkoutState.Rest) {
                            if (cleaned.isEmpty() || cleaned.last() is WorkoutState.Rest) continue
                        }
                        cleaned.add(st)
                    }
// strip any rest at the very start/end
                    while (cleaned.firstOrNull() is WorkoutState.Rest) cleaned.removeAt(0)
                    while (cleaned.lastOrNull() is WorkoutState.Rest)  cleaned.removeAt(cleaned.lastIndex)

                    totalStates.addAll(cleaned)
                }
            }
        }

        for (i in totalStates.indices) {
            val currentState = totalStates[i]
            if (currentState !is WorkoutState.Rest) continue

            val nextSets = mutableListOf<WorkoutState.Set>()

            // Look ahead until we find another Rest state or reach the end
            var j = i + 1
            while (j < totalStates.size) {
                val nextState = totalStates[j]
                if (nextState is WorkoutState.Rest) {
                    break
                }
                if (nextState is WorkoutState.Set) {
                    nextSets.add(nextState)
                }
                j++
            }

            // Update the Rest state with the collected nextSets
            currentState.nextStateSets = nextSets
        }

        return totalStates.toList()
    }

    protected fun getPlateChangeResults(
        exercise: Exercise,
        exerciseSets: List<Set>,
        equipment: WeightLoadedEquipment?,
        initialSetup: List<Double> = emptyList()
    ): List<PlateCalculator.Companion.PlateChangeResult> {
        val plateChangeResults = mutableListOf<PlateCalculator.Companion.PlateChangeResult>()

        if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
            val sets = exerciseSets.filterIsInstance<WeightSet>()
            val setWeights = sets.map { it.weight }.toList()
            val plateWeights = equipment.availablePlates.map { it.weight } .toList()

            try {
                val results = PlateCalculator.calculatePlateChanges(
                    plateWeights,
                    setWeights,
                    equipment.barWeight,
                    initialSetup,
                )

                plateChangeResults.addAll(results)
            } catch (e: Exception) {
                Log.e("PlatesCalculator", "Error calculating plate changes", e)
            }
        }

        return plateChangeResults
    }

    protected suspend fun addStatesFromExercise(exercise: Exercise) : List<WorkoutState> {
        if (exercise.sets.isEmpty()) return emptyList()

        val states = mutableListOf<WorkoutState>()

        val progressionData =
            if (exerciseProgressionByExerciseId.containsKey(exercise.id)) exerciseProgressionByExerciseId[exercise.id] else null

        val exerciseProgression = progressionData?.first
        val progressionState = progressionData?.second

        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
        val exerciseAllSets = mutableListOf<Set>()

        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exercise.id)

        val exerciseSets = exercise.sets

        if(exercise.generateWarmUpSets && equipment != null && (exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT)){
            // 1) Work set TOTAL (includes bar or BW)
            val (workWeightTotal, workReps) = exerciseSets.first().let {
                when (it) {
                    is BodyWeightSet -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                        // TOTAL = BW + extra
                        Pair(it.getWeight(relativeBodyWeight), it.reps)
                    }
                    is WeightSet -> {
                        // TOTAL = what you store as set.weight
                        Pair(it.weight, it.reps)
                    }
                    else -> throw IllegalArgumentException("Unknown set type")
                }
            }

            // 2) Available TOTALS for warmups (what WarmupPlanner expects)
            val availableTotals: kotlin.collections.Set<Double> = when (exercise.exerciseType) {
                ExerciseType.WEIGHT -> {
                    // IMPORTANT: this returns TOTALS including bar for barbells,
                    // or full stack totals for machines, etc.
                    // Use cached result to avoid recomputation
                    getCachedAvailableTotals(equipment)
                }
                ExerciseType.BODY_WEIGHT -> {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)

                    // equipment.getWeightsCombinations() gives extra load totals.
                    // Convert to TOTAL = BW + extra, plus pure BW.
                    // Use cached result to avoid recomputation
                    val extraTotals = getCachedAvailableTotals(equipment)
                    extraTotals.map { relativeBodyWeight + it }.toSet() + setOf(relativeBodyWeight)
                }
                else -> throw IllegalArgumentException("Unknown exercise type")
            }

            fun toSetInternalWeight(desiredTotal: Double): Double {
                return when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                        // BodyWeightSet stores extra load, TOTAL = BW + extra
                        desiredTotal - relativeBodyWeight
                    }
                    ExerciseType.WEIGHT -> {
                        // WeightSet stores TOTAL directly
                        desiredTotal
                    }
                    else -> throw IllegalArgumentException("Unknown exercise type")
                }
            }

            fun makeWarmupSet(id: UUID, total: Double, reps: Int): Set {
                val internalWeight = toSetInternalWeight(total)
                return when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> BodyWeightSet(id, reps, internalWeight, subCategory = SetSubCategory.WarmupSet)
                    ExerciseType.WEIGHT     -> WeightSet(id, reps, internalWeight, subCategory = SetSubCategory.WarmupSet)
                    else -> throw IllegalArgumentException("Unknown exercise type")
                }
            }

            // 3) Ask WarmupPlanner for TOTALS; it expects totals, not plate-only weights
            // For barbell exercises, use the plate-optimized version
            val warmups: List<Pair<Double, Int>> = if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
                WarmupPlanner.buildWarmupSetsForBarbell(
                    availableTotals = availableTotals,
                    workWeight = workWeightTotal,
                    workReps = workReps,
                    barbell = equipment,
                    initialSetup = emptyList(),
                    maxWarmups = 4
                )
            } else {
                WarmupPlanner.buildWarmupSets(
                    availableTotals = availableTotals,
                    workWeight = workWeightTotal,
                    workReps = workReps,
                    maxWarmups = 4
                )
            }

            // 4) Convert those TOTALS back into your Set objects
            warmups.forEach { (total, reps) ->
                val warmupSet = makeWarmupSet(UUID.randomUUID(), total, reps)
                exerciseAllSets.add(warmupSet)
                // Optional rest between warmups – keep as you had, or adjust
                exerciseAllSets.add(RestSet(UUID.randomUUID(), 60))
            }


            exerciseAllSets.addAll(exerciseSets)
        }else{
            exerciseAllSets.addAll(exerciseSets)
        }

        val plateChangeResults = getPlateChangeResults(exercise, exerciseAllSets, equipment)

        val weightSets = exerciseAllSets.filterIsInstance<WeightSet>()

        for ((index, set) in exerciseAllSets.withIndex()) {
            if (set is RestSet) {
                val restState = WorkoutState.Rest(
                    set = set,
                    order = index.toUInt(),
                    currentSetDataState = mutableStateOf(initializeSetData(set)),
                    exerciseId = exercise.id
                )
                states.add(restState)
            } else {
                var currentSetData = initializeSetData(set)

                if (currentSetData is BodyWeightSetData) {
                    currentSetData =
                        currentSetData.copy(relativeBodyWeightInKg = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100))
                    currentSetData =
                        currentSetData.copy(volume = currentSetData.calculateVolume())
                } else if (currentSetData is WeightSetData) {
                    currentSetData =
                        currentSetData.copy(volume = currentSetData.calculateVolume())
                }

                var previousSetData = copySetData(currentSetData)

                val historySet =
                    if (exercise.doNotStoreHistory) null else latestSetHistoryMap[set.id];

                if (historySet != null) {
                    val historySetData = historySet.setData
                    if (isSetDataValid(set, historySetData) && exerciseProgression == null) {
                        currentSetData = copySetData(historySetData)
                        previousSetData = historySet.setData
                    }
                }

                val weightSetIndex = weightSets.indexOf(set)
                val plateChangeResult = plateChangeResults.getOrNull(weightSetIndex)

                val isWarmupSet = when(set) {
                    is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    else -> false
                }

                val isUnilateral = exercise.intraSetRestInSeconds != null && exercise.intraSetRestInSeconds > 0

                val setState: WorkoutState.Set = WorkoutState.Set(
                    exercise.id,
                    set,
                    index.toUInt(),
                    previousSetData,
                    currentSetDataState = mutableStateOf(currentSetData),
                    historySet == null,
                    startTime = null,
                    false,
                    lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
                    bodyWeight.value,
                    plateChangeResult,
                    exerciseInfo?.successfulSessionCounter?.toInt() ?: 0,
                    progressionState,
                    isWarmupSet,
                    exercise.equipmentId?.let { getEquipmentById(it) },
                    isUnilateral = isUnilateral
                )



                if(!isWarmupSet && isUnilateral){
                    val restDuration = exercise.intraSetRestInSeconds!!
                    val restSet = RestSet(UUID.randomUUID(), restDuration)
                    val restState = WorkoutState.Rest(
                        set = restSet,
                        order = index.toUInt(),
                        currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                        nextStateSets = listOf(setState),
                        exerciseId = exercise.id,
                        isIntraSetRest = true
                    )

                    val newSetState = setState.copy(isUnilateral = true, intraSetTotal = 2u, intraSetCounter = 1u)

                    states.add(newSetState)
                    states.add(restState)
                    states.add(newSetState)
                }else{
                    states.add(setState)
                }
            }
        }

        return states
    }

    fun setWorkoutStart() {
        val startTime = LocalDateTime.now()
        startWorkoutTime = startTime
        
        // Add Completed state to state machine if it exists
        val machine = stateMachine
        if (machine != null && !machine.isCompleted) {
            // Create new state machine with Completed state added
            val statesWithCompleted = machine.allStates.toMutableList()
            statesWithCompleted.add(WorkoutState.Completed(startWorkoutTime!!))
            stateMachine = WorkoutStateMachine(statesWithCompleted, machine.currentIndex) { LocalDateTime.now() }
            updateStateFlowsFromMachine()
        } else if (machine == null && allWorkoutStates.isNotEmpty()) {
            // Fallback: initialize state machine if it wasn't initialized yet
            stateMachine = initializeStateMachine(allWorkoutStates)
            updateStateFlowsFromMachine()
        }
        rebuildScreenState()
    }

    /**
     * Checks if the next state after the current state is WorkoutState.Completed.
     * Used to determine if we're completing the last set in the workout.
     */
    fun isNextStateCompleted(): Boolean {
        val machine = stateMachine ?: return false
        return machine.upcomingNext is WorkoutState.Completed
    }

    open fun goToNextState() {
        val machine = stateMachine ?: return
        if (machine.isCompleted) return

        stateMachine = machine.next()
        updateStateFlowsFromMachine()
    }

    fun goToPreviousSet() {
        val machine = stateMachine ?: return
        if (machine.isAtStart) return

        val currentState = machine.currentState
        
        // Return early if current state is Preparing or Completed
        if (currentState is WorkoutState.Preparing || currentState is WorkoutState.Completed) {
            return
        }

        // Get current set.id (works for both Set and Rest states)
        val currentSetId = when (currentState) {
            is WorkoutState.Set -> currentState.set.id
            is WorkoutState.Rest -> currentState.set.id
            else -> return
        }

        // Search backwards through allStates to find the previous Set state with different set.id
        // Start from currentIndex - 1 (the state before current) and go backwards to 0
        var targetIndex = -1
        for (i in machine.currentIndex - 1 downTo 0) {
            val state = machine.allStates[i]
            if (state is WorkoutState.Set) {
                // Found a Set state - check if it has a different set.id
                if (state.set.id != currentSetId) {
                    targetIndex = i
                    break
                }
            }
            // Skip Rest states and continue searching
        }

        // If no previous Set state found, return early
        if (targetIndex < 0) {
            return
        }

        // Navigate directly to the target Set state
        stateMachine = WorkoutStateMachine(machine.allStates, targetIndex) { LocalDateTime.now() }
        updateStateFlowsFromMachine()

        // Clean up executedSetsHistory: remove all entries that correspond to sets after the target Set
        viewModelScope.launch(dispatchers.io) {
            // Get all setIds that come after the target Set in allStates
            val setIdsToRemove = mutableSetOf<UUID>()
            for (i in targetIndex + 1 until machine.allStates.size) {
                val state = machine.allStates[i]
                when (state) {
                    is WorkoutState.Set -> setIdsToRemove.add(state.set.id)
                    is WorkoutState.Rest -> setIdsToRemove.add(state.set.id)
                    else -> { /* Skip Preparing and Completed */ }
                }
            }

            // Remove all SetHistory entries that match any of the setIds to remove
            val currentList = executedSetStore.executedSets.value.toMutableList()
            val filteredList = currentList.filterNot { setHistory ->
                setHistory.setId in setIdsToRemove
            }
            
            if (filteredList.size < currentList.size) {
                executedSetStore.replaceAll(filteredList)
            }
        }
    }

    fun goToNextExercise() {
        val machine = stateMachine ?: return
        val currentState = _workoutState.value as? WorkoutState.Set ?: return
        val currentExerciseId = currentState.exerciseId

        // Skip until we find a Set with different exerciseId or Completed state
        val newMachine = machine.skipUntil { state ->
            (state is WorkoutState.Set && state.exerciseId != currentExerciseId) ||
            state is WorkoutState.Completed
        }

        stateMachine = newMachine
        updateStateFlowsFromMachine()
    }
}
