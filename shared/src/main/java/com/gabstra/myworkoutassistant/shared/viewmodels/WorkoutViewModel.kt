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
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.workout.assembly.WorkoutSetPreparationService
import com.gabstra.myworkoutassistant.shared.workout.assembly.WorkoutSetStateFactory
import com.gabstra.myworkoutassistant.shared.workout.assembly.WorkoutSupersetAssemblyService
import com.gabstra.myworkoutassistant.shared.workout.plates.PlateRecalculationDebouncer
import com.gabstra.myworkoutassistant.shared.workout.persistence.WorkoutPersistenceCoordinator
import com.gabstra.myworkoutassistant.shared.workout.persistence.WorkoutRecordService
import com.gabstra.myworkoutassistant.shared.workout.progression.SessionDecision
import com.gabstra.myworkoutassistant.shared.workout.progression.WorkoutProgressionService
import com.gabstra.myworkoutassistant.shared.workout.state.CalibrationContext
import com.gabstra.myworkoutassistant.shared.workout.state.CalibrationPhase
import com.gabstra.myworkoutassistant.shared.workout.state.ContainerPosition
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateEditor
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceOps
import com.gabstra.myworkoutassistant.shared.workout.session.WorkoutRefreshService
import com.gabstra.myworkoutassistant.shared.workout.session.WorkoutResumptionService
import com.gabstra.myworkoutassistant.shared.workout.session.WorkoutSessionLifecycleService
import com.gabstra.myworkoutassistant.shared.workout.session.WorkoutSessionOrchestrator
import com.gabstra.myworkoutassistant.shared.workout.session.WorkoutTimerRestoreService
import com.gabstra.myworkoutassistant.shared.workout.timer.WorkoutTimerService
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutScreenState
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutSessionPhase
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.WarmupContext
import com.gabstra.myworkoutassistant.shared.utils.WarmupContextBuilder
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.coroutines.EmptyCoroutineContext
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
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
    internal val dispatchers: DispatcherProvider = DefaultDispatcherProvider,
    private val executedSetStore: ExecutedSetStore = DefaultExecutedSetStore()
) : ViewModel() {
    companion object {
        private const val TAG = "WorkoutViewModel"
    }

    /** Optional handler for unhandled coroutine exceptions (e.g. set by Wear OS to log to file). */
    protected var coroutineExceptionHandler: CoroutineExceptionHandler? = null
        set(value) {
            field = value
        }

    /** CoroutineContext containing the optional exception handler; use when launching root coroutines. */
    protected open fun exceptionContext(): CoroutineContext =
        coroutineExceptionHandler ?: EmptyCoroutineContext

    fun launchMain(block: suspend CoroutineScope.() -> Unit): Job =
        viewModelScope.launch(exceptionContext() + dispatchers.main, block = block)

    fun launchIO(block: suspend CoroutineScope.() -> Unit): Job =
        viewModelScope.launch(exceptionContext() + dispatchers.io, block = block)

    fun launchDefault(block: suspend CoroutineScope.() -> Unit): Job =
        viewModelScope.launch(exceptionContext(), block = block)

    private var storeSetDataJob: Job? = null
    private val workoutRecordMutex = Mutex()
    private val workoutPersistenceCoordinator by lazy {
        WorkoutPersistenceCoordinator(
            executedSetStore = executedSetStore,
            workoutHistoryDao = { workoutHistoryDao },
            setHistoryDao = { setHistoryDao },
            exerciseInfoDao = { exerciseInfoDao },
            exerciseSessionProgressionDao = { exerciseSessionProgressionDao },
            workoutStoreRepository = { workoutStoreRepository }
        )
    }
    private val workoutRecordService by lazy {
        WorkoutRecordService(
            workoutRecordDao = { workoutRecordDao },
            workoutHistoryDao = { workoutHistoryDao }
        )
    }
    private val workoutRefreshService = WorkoutRefreshService()
    private val workoutResumptionService = WorkoutResumptionService()
    private val workoutSessionLifecycleService by lazy {
        WorkoutSessionLifecycleService(
            executedSetStore = executedSetStore,
            setHistoryDao = { setHistoryDao },
            workoutHistoryDao = { workoutHistoryDao }
        )
    }
    private val workoutSessionOrchestrator = WorkoutSessionOrchestrator()
    private val workoutTimerRestoreService = WorkoutTimerRestoreService()
    private val workoutSetStateFactory = WorkoutSetStateFactory()
    private val workoutSetPreparationService = WorkoutSetPreparationService()
    private val workoutSupersetAssemblyService = WorkoutSupersetAssemblyService()
    private val workoutProgressionService by lazy {
        WorkoutProgressionService(
            exerciseInfoDao = { exerciseInfoDao },
            setHistoryDao = { setHistoryDao },
            workoutHistoryDao = { workoutHistoryDao },
            exerciseSessionProgressionDao = { exerciseSessionProgressionDao }
        )
    }

    /**
     * Synchronously flush timer state to database.
     * Should be called on app lifecycle events (onPause/onStop) to ensure timer state is persisted.
     * This prevents loss of timer progress when app is closed mid-timer.
     */
    suspend fun flushTimerState() {
        // Wait for any pending storeSetData job to complete first.
        storeSetDataJob?.join()
        val snapshot = withContext(dispatchers.main) {
            workoutPersistenceCoordinator.captureSetHistorySnapshot(
                currentState = _workoutState.value,
                exercisesById = exercisesById
            )
        }
        withContext(dispatchers.io) {
            snapshot?.let { workoutPersistenceCoordinator.upsertSetHistorySnapshot(it) }
            Log.d(TAG, "Timer state flushed to database")
        }
    }

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
        if (_currentScreenDimmingState.value != shouldDim) {
            _currentScreenDimmingState.value = shouldDim
            rebuildScreenState()
        }
    }

    fun lightScreenUp() {
        launchMain {
            _lightScreenUp.send(Unit)
        }
    }

    fun reEvaluateDimmingForCurrentState() {
        val currentState = workoutState.value
        val newDimming = when (currentState) {
            is WorkoutState.Set -> {
                val exercise = exercisesById[currentState.exerciseId]!!
                !exercise.keepScreenOn
            }
            is WorkoutState.Rest -> true
            else -> return
        }
        if (_currentScreenDimmingState.value != newDimming) {
            _currentScreenDimmingState.value = newDimming
            rebuildScreenState()
        }
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
            measuredMaxHeartRate = null,
            restingHeartRate = null,
        )
    )

    var lastSessionWorkout by mutableStateOf<Workout?>(null)

    fun getEquipmentById(id: UUID): WeightLoadedEquipment? {
        // Capture workoutStore value to avoid race conditions with state access
        val currentWorkoutStore = workoutStore
        return currentWorkoutStore.equipments.find { it.id == id }
    }

    fun getAccessoryEquipmentById(id: UUID): AccessoryEquipment? {
        // Capture workoutStore value to avoid race conditions with state access
        val currentWorkoutStore = workoutStore
        return currentWorkoutStore.accessoryEquipments.find { it.id == id }
    }

    private val _isPaused = mutableStateOf(false) // Private mutable state
    open val isPaused: State<Boolean> = _isPaused // read-only State access

    // Timer service for managing workout timers independently of composable lifecycle
    val workoutTimerService = WorkoutTimerService(
        viewModelScope = CoroutineScope(viewModelScope.coroutineContext + exceptionContext()),
        isPaused = { _isPaused.value }
    )

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

    // Plate recalculation debouncer and state
    private val plateRecalculationDebouncer = PlateRecalculationDebouncer(viewModelScope, debounceDelayMs = 400L)
    private var lastPlateRecalculationWeight: Double? = null
    private val _isPlateRecalculationInProgress = MutableStateFlow(false)
    val isPlateRecalculationInProgress = _isPlateRecalculationInProgress.asStateFlow()

    private var _backupProgress = mutableStateOf(0f)
    val backupProgress: State<Float> = _backupProgress

    private var _selectedWorkoutId = mutableStateOf<UUID?>(null)
    val selectedWorkoutId: State<UUID?> get() = _selectedWorkoutId

    // Create a function to update the backup progress
    fun setBackupProgress(progress: Float) {
        _backupProgress.value = progress
    }

    val allWorkoutStates: List<WorkoutState>
        get() = stateMachine?.allStates ?: emptyList()

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
                measuredMaxHeartRate = null,
                restingHeartRate = null,
            )
        )
    }

    fun updateWorkoutStore(newWorkoutStore: WorkoutStore) {
        workoutStore = newWorkoutStore
        // Use newWorkoutStore directly to avoid potential race condition with state access
        _workouts.value = newWorkoutStore.workouts.filter { it.enabled && it.isActive }
        val currentYear = Calendar.getInstance().get(Calendar.YEAR)
        _userAge.intValue = currentYear - newWorkoutStore.birthDateYear
        _bodyWeight.value = newWorkoutStore.weightKg.toDouble()
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

    internal lateinit var exerciseInfoDao: ExerciseInfoDao

    /** Protected accessor for subclasses in other modules (e.g. wearos AppViewModel). */
    protected fun getExerciseInfoDao(): ExerciseInfoDao = exerciseInfoDao

    protected lateinit var exerciseSessionProgressionDao: ExerciseSessionProgressionDao

    protected lateinit var workoutStoreRepository: WorkoutStoreRepository

    private val _workoutState =
        MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()
    private val _sessionPhase = MutableStateFlow(WorkoutSessionPhase.PREPARING)
    val sessionPhase = _sessionPhase.asStateFlow()

    /**
     * Single source of truth for "we are in calibration" and where the calibration set lives.
     * Set when current state is CalibrationLoadSelection, Set(isCalibrationSet), or CalibrationRIRSelection; cleared otherwise.
     */
    private val _calibrationContext = MutableStateFlow<CalibrationContext?>(null)
    val calibrationContext = _calibrationContext.asStateFlow()

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
    internal var stateMachine: WorkoutStateMachine? = null

    /**
     * Read-only access to workout state history for external consumers.
     * Returns an immutable snapshot of the current history.
     */
    val workoutStateHistory: List<WorkoutState>
        get() = stateMachine?.history ?: emptyList()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    internal val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    val latestSetHistoriesByExerciseId: MutableMap<UUID, List<SetHistory>> = mutableMapOf()

    /**
     * Initializes the state machine from the hierarchical workout sequence.
     * The machine navigates only flattened in-sequence states; Preparing/Completed stay outside the machine.
     */
    /**
     * Applies executed set data to states in the sequence.
     */
    private fun applyExecutedSetDataToSequence(
        sequence: List<WorkoutStateSequenceItem>,
        executedSetsHistorySnapshot: List<SetHistory>
    ): List<WorkoutStateSequenceItem> {
        return WorkoutStateEditor.applyExecutedSetDataToSequence(
            sequence = sequence,
            executedSetsHistorySnapshot = executedSetsHistorySnapshot
        )
    }

    private fun initializeStateMachine(sequence: List<WorkoutStateSequenceItem>, startIndex: Int = 0): WorkoutStateMachine {
        val finalSequence = sequence

        // Calculate adjusted startIndex
        val finalAllStates = finalSequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> WorkoutStateSequenceOps.flattenExerciseContainer(container)
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
            }
        }

        val adjustedStartIndex = startIndex.coerceIn(0, finalAllStates.size - 1)
        
        return WorkoutStateMachine.fromSequence(finalSequence, { LocalDateTime.now() }, adjustedStartIndex)
    }

    /**
     * Updates the state flows from the current state machine.
     * Also updates [calibrationContext] from the current state so UI and apply logic can use it without scanning.
     */
    internal fun updateStateFlowsFromMachine() {
        val machine = stateMachine
        if (machine != null) {
            _workoutState.value = machine.currentState
            _nextWorkoutState.value = machine.upcomingNext
            _isHistoryEmpty.value = machine.isHistoryEmpty
            _sessionPhase.value = WorkoutSessionPhase.ACTIVE
            _calibrationContext.value = calibrationContextFromState(machine)
        } else {
            _calibrationContext.value = null
        }
        rebuildScreenState()
    }

    /**
     * Derives calibration context from the current state machine state.
     * Called from [updateStateFlowsFromMachine]; also used when inserting CalibrationRIRSelection to set execution index.
     */
    private fun calibrationContextFromState(machine: WorkoutStateMachine): CalibrationContext? {
        val state = machine.currentState
        val stateExerciseId = WorkoutStateQueries.stateExerciseId(state)
        val stateSetId = WorkoutStateQueries.stateSetId(state)
        val directContext = when (state) {
            is WorkoutState.CalibrationLoadSelection -> CalibrationContext(
                exerciseId = stateExerciseId ?: return null,
                calibrationSetId = stateSetId ?: return null,
                phase = CalibrationPhase.LOAD_SELECTION,
                calibrationSetExecutionStateIndex = null
            )
            is WorkoutState.Set -> if (state.isCalibrationSet) {
                CalibrationContext(
                    exerciseId = stateExerciseId ?: return null,
                    calibrationSetId = stateSetId ?: return null,
                    phase = CalibrationPhase.EXECUTING,
                    calibrationSetExecutionStateIndex = machine.currentIndex
                )
            } else null
            is WorkoutState.CalibrationRIRSelection -> CalibrationContext(
                exerciseId = stateExerciseId ?: return null,
                calibrationSetId = stateSetId ?: return null,
                phase = CalibrationPhase.RIR_SELECTION,
                calibrationSetExecutionStateIndex = machine.currentIndex - 1
            )
            else -> null
        }
        if (directContext != null) return directContext

        val position = machine.getContainerAndChildIndex(machine.currentIndex) as? ContainerPosition.Exercise
            ?: return null
        val container = machine.getCurrentExerciseContainer() ?: return null
        val currentChildItem = container.childItems.getOrNull(position.childItemIndex) ?: return null

        val calibrationExecutionIndex = machine.allStates.indexOfFirst {
            it is WorkoutState.Set &&
                it.isCalibrationSet &&
                WorkoutStateQueries.stateExerciseId(it) == container.exerciseId
        }.takeIf { it >= 0 }

        val calibrationSetId = machine.allStates
            .filterIsInstance<WorkoutState.Set>()
            .firstOrNull {
                it.isCalibrationSet && WorkoutStateQueries.stateExerciseId(it) == container.exerciseId
            }?.set?.id ?: stateSetId

        if (calibrationSetId == null) return null

        return when (currentChildItem) {
            is ExerciseChildItem.LoadSelectionBlock -> CalibrationContext(
                exerciseId = container.exerciseId,
                calibrationSetId = calibrationSetId,
                phase = CalibrationPhase.LOAD_SELECTION,
                calibrationSetExecutionStateIndex = calibrationExecutionIndex
            )
            else -> null
        }
    }

    /**
     * Clears calibration context. Call when calibration is finished (e.g. after applyCalibrationRIR) or when navigating away.
     */
    internal fun clearCalibrationContext() {
        _calibrationContext.value = null
    }

    /** Current calibration context value for use in applyCalibrationRIR and other extensions. */
    internal fun getCalibrationContextValue(): CalibrationContext? = _calibrationContext.value

    protected fun enterPreparingPhase() {
        _sessionPhase.value = WorkoutSessionPhase.PREPARING
        _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
    }

    protected fun markSessionReady() {
        _sessionPhase.value = WorkoutSessionPhase.READY
        _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
    }

    /**
     * Rebuilds the WorkoutScreenState from current ViewModel fields.
     * Call this whenever any UI-observable field changes.
     * Only emits if the new state differs from the current state to prevent unnecessary recompositions.
     */
    protected open fun rebuildScreenState() {
        val newState = WorkoutScreenState(
            workoutState = _workoutState.value,
            sessionPhase = _sessionPhase.value,
            nextWorkoutState = _nextWorkoutState.value,
            selectedWorkout = _selectedWorkout.value,
            isPaused = _isPaused.value,
            hasWorkoutRecord = _hasWorkoutRecord.value,
            isResuming = _isResuming.value,
            isRefreshing = _isRefreshing.value,
            isCustomDialogOpen = _isCustomDialogOpen.value,
            enableWorkoutNotificationFlow = _enableWorkoutNotificationFlow.value,
            userAge = _userAge.intValue,
            measuredMaxHeartRate = workoutStore.measuredMaxHeartRate,
            restingHeartRate = workoutStore.restingHeartRate,
            startWorkoutTime = startWorkoutTime,
            enableDimming = enableDimming.value,
            keepScreenOn = _keepScreenOn.value,
            currentScreenDimmingState = _currentScreenDimmingState.value,
            headerDisplayMode = 0, // Default for base WorkoutViewModel, overridden in AppViewModel
            hrDisplayMode = 0, // Default for base WorkoutViewModel, overridden in AppViewModel
        )
        
        // Only emit if state actually changed
        if (_screenState.value != newState) {
            _screenState.value = newState
        }
    }

    private data class SetKey(val exerciseId: UUID, val setId: UUID)
    private val latestSetHistoryMap: MutableMap<SetKey, SetHistory> = mutableMapOf()

    protected val weightsByEquipment: MutableMap<WeightLoadedEquipment, kotlin.collections.Set<Double>> =
        mutableMapOf()

    // Cache for available totals (getWeightsCombinationsNoExtra results) per equipment ID
    private val availableTotalsCache: MutableMap<UUID, kotlin.collections.Set<Double>> =
        mutableMapOf()

    fun getWeightByEquipment(equipment: WeightLoadedEquipment?): kotlin.collections.Set<Double> {
        if (equipment == null) return emptySet()
        return weightsByEquipment[equipment] ?: emptySet()
    }

    internal fun getCachedAvailableTotals(equipment: WeightLoadedEquipment): kotlin.collections.Set<Double> {
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
        get() = allWorkoutStates
            .filterIsInstance<WorkoutState.Set>()
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
        // Capture workoutStore value to avoid race conditions with state access
        val currentWorkoutStore = workoutStore
        val workout = currentWorkoutStore.workouts.find { it.id == workoutId }
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
        workoutTimerService.unregisterAll()
        resetWorkoutStore()
        workoutStoreRepository.saveWorkoutStore(workoutStore)
        launchMain {
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
        launchMain {
            val recordState = withContext(dispatchers.io) {
                workoutRecordService.resolveWorkoutRecord(workout.id)
            }
            _workoutRecord = recordState.workoutRecord
            _hasWorkoutRecord.value = recordState.hasWorkoutRecord
            _isCheckingWorkoutRecord.value = false
            rebuildScreenState()
        }
    }

    fun upsertWorkoutRecord(exerciseId : UUID,setIndex: UInt) {
        val selectedWorkoutIdSnapshot = selectedWorkout.value.id
        val workoutHistoryIdSnapshot = currentWorkoutHistory?.id
        val existingRecordSnapshot = _workoutRecord
        launchIO {
            var updatedRecord: WorkoutRecord? = null
            workoutRecordMutex.withLock {
                updatedRecord = workoutRecordService.upsertWorkoutRecord(
                    existingRecord = existingRecordSnapshot,
                    workoutId = selectedWorkoutIdSnapshot,
                    workoutHistoryId = workoutHistoryIdSnapshot,
                    exerciseId = exerciseId,
                    setIndex = setIndex
                )
            }

            withContext(dispatchers.main) {
                if (updatedRecord != null) {
                    _workoutRecord = updatedRecord
                    _hasWorkoutRecord.value = true
                }
                rebuildScreenState()
            }
        }
    }

    fun deleteWorkoutRecord() {
        val recordIdToDelete = _workoutRecord?.id ?: return
        launchIO {
            workoutRecordMutex.withLock {
                workoutRecordService.deleteWorkoutRecord(recordIdToDelete)
            }

            withContext(dispatchers.main) {
                if (_workoutRecord?.id == recordIdToDelete) {
                    _workoutRecord = null
                    _hasWorkoutRecord.value = false
                    rebuildScreenState()
                }
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
            // Capture workoutStore value at the start to avoid race conditions
            val currentWorkoutStore = workoutStore
            workoutRecordService.getIncompleteWorkouts(currentWorkoutStore.workouts).map { incomplete ->
                IncompleteWorkout(
                    workoutHistory = incomplete.workoutHistory,
                    workoutName = incomplete.workoutName,
                    workoutId = incomplete.workoutId
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
        return workoutResumptionService.findResumptionIndex(
            allWorkoutStates = allWorkoutStates,
            executedSetsHistorySnapshot = executedSetsHistorySnapshot,
            workoutRecord = _workoutRecord,
            exercisesById = exercisesById
        )
    }

    open fun resumeWorkoutFromRecord(onEnd: suspend () -> Unit = {}) {
        launchMain {
            withContext(dispatchers.io) {
                _enableWorkoutNotificationFlow.value = null
                _currentScreenDimmingState.value = false

                enterPreparingPhase()
                stateMachine = null
                setStates.clear()
                weightsByEquipment.clear()
                _isPaused.value = false
                val resumeSelectedWorkout = workoutSessionOrchestrator.selectWorkout(
                    workouts = _workouts.value,
                    selectedWorkoutId = _selectedWorkoutId.value
                ) ?: return@withContext
                _selectedWorkout.value = resumeSelectedWorkout
                rebuildScreenState()

                val resumeHistoryId = workoutSessionOrchestrator.resolveResumeHistoryId(
                    pendingResumeWorkoutHistoryId = pendingResumeWorkoutHistoryId,
                    workoutRecord = _workoutRecord
                )
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
                _hasWorkoutRecord.value = true

                heartBeatHistory.addAll(currentWorkoutHistory!!.heartBeatRecords)
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(currentWorkoutHistory!!.id)
                startWorkoutTime = workoutSessionOrchestrator.deriveStartWorkoutTimeFromCompletedSetHistories(setHistories)

                restoreExecutedSets()
                loadWorkoutHistory()

                preProcessExercises()
                generateProgressions()
                applyProgressions()
                val workoutSequence = generateWorkoutStates()

                // Take a snapshot of executedSetsHistory (immutable from StateFlow)
                val executedSetsHistorySnapshot = executedSetStore.executedSets.value

                // Apply executed set data to states in containers
                val updatedSequence = applyExecutedSetDataToSequence(workoutSequence, executedSetsHistorySnapshot)

                val resumptionIndex = workoutSessionOrchestrator.computeResumptionIndex(
                    updatedSequence = updatedSequence,
                    executedSetsHistorySnapshot = executedSetsHistorySnapshot,
                    resolveIndex = ::findResumptionIndex
                )
                
                // Initialize state machine with sequence at the correct resumption index
                val machine = initializeStateMachine(updatedSequence, resumptionIndex)
                // Populate nextState for Rest states
                populateNextStateForRest(machine)
                stateMachine = machine
                // Populate setStates from allWorkoutStates
                populateNextStateSets()
                markSessionReady()
                triggerWorkoutNotification()
                onEnd()
            }
        }
    }

    fun getAllExerciseWorkoutStates(exerciseId: UUID): List<WorkoutState.Set> {
        return allWorkoutStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }
    }

    /**
     * Returns the ordered list of workout states associated with the exercise (from the exercise's
     * container in the state machine: ExerciseState.childStates or filtered SupersetState.childStates).
     * Includes Set, CalibrationLoadSelection, and CalibrationRIRSelection in schedule order.
     */
    fun getStatesForExercise(exerciseId: UUID): List<WorkoutState> {
        val machine = stateMachine ?: return emptyList()
        return WorkoutStateQueries.statesForExercise(machine, exerciseId)
    }

    /**
     * Returns the total number of logical sets for an exercise, from the state machine.
     * Counts Set states only (including calibration execution sets; unilateral counts once).
     */
    fun getTotalSetCountForExercise(exerciseId: UUID): Int {
        val exerciseStates = getStatesForExercise(exerciseId)
        return WorkoutStateQueries.orderedUniqueLogicalSetIds(exerciseStates).size
    }

    /**
     * Returns (currentSetIndex1Based, totalSetCount) for the given exercise and current state.
     * Uses the state machine's exercise states as source of truth (not exercise.sets, which can be updated).
     * Handles any state that maps to a counted set id.
     * Returns null when the current state does not represent a set (e.g. Rest) or is not for this exercise.
     */
    fun getSetCounterForExercise(exerciseId: UUID, currentState: WorkoutState): Pair<Int, Int>? {
        val total = getTotalSetCountForExercise(exerciseId)
        if (total == 0) return null
        val exerciseStates = getStatesForExercise(exerciseId)
        val orderedSetIds = WorkoutStateQueries.orderedUniqueLogicalSetIds(exerciseStates)
        val currentExerciseId = WorkoutStateQueries.stateExerciseId(currentState)
        if (currentExerciseId != exerciseId) return null
        val currentSetId = WorkoutStateQueries.stateSetId(currentState) ?: return null
        val currentIndex = orderedSetIds.indexOf(currentSetId)
        return if (currentIndex >= 0) Pair(currentIndex + 1, total) else null
    }

    suspend fun createStatesFromExercise(exercise: Exercise): List<WorkoutState> {
        return addStatesFromExercise(exercise, priorExercises = emptyList()).flatMap { item ->
            when (item) {
                is ExerciseChildItem.Normal -> listOf(item.state)
                is ExerciseChildItem.CalibrationExecutionBlock -> item.childStates
                is ExerciseChildItem.LoadSelectionBlock -> item.childStates
                is ExerciseChildItem.UnilateralSetBlock -> item.childStates
            }
        }
    }

    fun getAllExerciseCompletedSetsBefore(target: WorkoutState.Set): List<WorkoutState.Set> {
        // Find all indices where sets with matching set.id appear
        val targetSetId = target.set.id
        val matchingIndices = allWorkoutStates.mapIndexedNotNull { index, state ->
            if (state is WorkoutState.Set && WorkoutStateQueries.stateSetId(state) == targetSetId) {
                index
            } else null
        }
        
        if (matchingIndices.isEmpty()) return emptyList()
        
        // Determine which occurrence corresponds to the current position in workout flow
        val currentWorkoutState = _workoutState.value
        
        // Count how many matching sets have been completed (are in history)
        // This tells us which occurrence we're currently on (0-indexed)
        val completedMatchingSetsCount = workoutStateHistory.count { 
            it is WorkoutState.Set && it.set.id == targetSetId
        }
        
        val cutoff: Int = if (target === currentWorkoutState) {
            // If target is the current state, use the occurrence index based on completed count
            // For unilateral sets: if 0 completed, we're on first occurrence; if 1 completed, we're on second
            val occurrenceIndex = completedMatchingSetsCount.coerceAtMost(matchingIndices.size - 1)
            matchingIndices[occurrenceIndex]
        } else {
            // If target is not the current state, determine its position
            val targetIndexInHistory = workoutStateHistory.indexOfFirst { state ->
                WorkoutStateQueries.stateSetId(state) == targetSetId || state === target
            }
            if (targetIndexInHistory >= 0) {
                // Target is in history, so it's been completed
                // Count how many matching sets appear before target in history
                val matchingSetsBeforeTargetInHistory = workoutStateHistory
                    .subList(0, targetIndexInHistory)
                    .count { WorkoutStateQueries.stateSetId(it) == targetSetId }
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
            return@withContext workoutSessionLifecycleService.getLastCompletedWorkoutExecutedSets(
                workoutGlobalId = selectedWorkout.value.globalId,
                currentWorkoutHistoryId = currentWorkoutHistory?.id,
                exerciseId = exerciseId
            )
        }
    }

    private suspend fun preProcessExercises() {
        val exercises =
            selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
        val validExercises = exercises.filter { exercise ->
            !exercise.doNotStoreHistory &&
                exercise.enableProgression &&
                !exercise.requiresLoadCalibration
        }
        val latestSetHistoryByKey = latestSetHistoryMap.entries.associate { (key, value) ->
            (key.exerciseId to key.setId) to value
        }
        validExercises.forEach { exercise ->
            val sessionDecision = computeSessionDecision(exercise.id)
            val validSets = workoutProgressionService.buildPreProcessedSets(
                exercise = exercise,
                latestSetHistoryByKey = latestSetHistoryByKey,
                sessionDecision = sessionDecision
            )
            updateWorkout(
                exercise,
                exercise.copy(
                    sets = validSets,
                    requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList()
                )
            )
        }
        lastSessionWorkout = _selectedWorkout.value.copy()
    }

    private fun applyProgressions() {
        val exercises =
            selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
        val validExercises = exercises.filter { exercise ->
            exercise.enabled &&
                exercise.enableProgression &&
                !exercise.requiresLoadCalibration &&
                !exercise.doNotStoreHistory &&
                exerciseProgressionByExerciseId.containsKey(exercise.id)
        }
        validExercises.forEach { exercise ->
            val exerciseProgression = exerciseProgressionByExerciseId[exercise.id]!!.first
            val newExercise = workoutProgressionService.buildExerciseWithProgression(
                exercise = exercise,
                plan = exerciseProgression,
                bodyWeightKg = bodyWeight.value
            )
            updateWorkout(exercise, newExercise)
        }
        initializeExercisesMaps(selectedWorkout.value)
    }

    protected suspend fun generateProgressions() {
        val generationResult = workoutProgressionService.generateProgressions(
            selectedWorkout = selectedWorkout.value,
            bodyWeightKg = bodyWeight.value,
            getEquipmentById = ::getEquipmentById,
            getWeightByEquipment = ::getWeightByEquipment,
            weightsByEquipment = weightsByEquipment
        )
        exerciseProgressionByExerciseId.clear()
        exerciseProgressionByExerciseId.putAll(generationResult.progressionByExerciseId)
        plateauReasonByExerciseId.clear()
        plateauReasonByExerciseId.putAll(generationResult.plateauReasonByExerciseId)
    }

    suspend fun computeSessionDecision(
        exerciseId: UUID,
    ): SessionDecision {
        return workoutProgressionService.computeSessionDecision(exerciseId)
    }

    fun resumeLastState() {
        if (_workoutRecord == null) return
        val executedSetHistories = executedSetStore.executedSets.value

        fun isTargetResumeState(state: WorkoutState?): Boolean {
            if (state !is WorkoutState.Set) return false
            return WorkoutStateQueries.matchesExerciseAndOrder(
                state = state,
                exerciseId = _workoutRecord!!.exerciseId,
                order = _workoutRecord!!.setIndex
            )
        }

        // When we land on Preparing before resuming, the state machine already knows the real state.
        // Sync the UI-facing state so comparisons run against the latest value.
        if (_workoutState.value is WorkoutState.Preparing && stateMachine != null) {
            updateStateFlowsFromMachine()
        }

        val currentState = _workoutState.value
        if (isTargetResumeState(currentState) && currentState is WorkoutState.Set) {
            workoutTimerRestoreService.restoreTimerForTimeSet(currentState, executedSetHistories, TAG)
            return
        }

        launchIO {
            _isResuming.value = true
            while (true) {
                if (_workoutState.value is WorkoutState.Completed) break
                val machineState = stateMachine?.currentState ?: break

                if (isTargetResumeState(machineState) && machineState is WorkoutState.Set) {
                    workoutTimerRestoreService.restoreTimerForTimeSet(machineState, executedSetHistories, TAG)
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

    /**
     * Attempts to move the current state machine pointer to a recovery target.
     * Returns true when a matching state was found and selected.
     */
    fun moveToRecoveredState(
        stateType: String,
        exerciseId: UUID?,
        setId: UUID?,
        setIndex: UInt?,
        restOrder: UInt?
    ): Boolean {
        val machine = stateMachine ?: return false
        if (machine.allStates.isEmpty()) return false

        val targetIndex = findRecoveryStateIndex(
            allStates = machine.allStates,
            stateType = stateType,
            exerciseId = exerciseId,
            setId = setId,
            setIndex = setIndex,
            restOrder = restOrder
        ) ?: return false

        stateMachine = machine.withCurrentIndex(targetIndex)
        updateStateFlowsFromMachine()

        val setState = _workoutState.value as? WorkoutState.Set
        if (setState != null) {
            val executedSetHistories = executedSetStore.executedSets.value
            workoutTimerRestoreService.restoreTimerForTimeSet(setState, executedSetHistories, TAG)
        }

        return true
    }

    private fun findRecoveryStateIndex(
        allStates: List<WorkoutState>,
        stateType: String,
        exerciseId: UUID?,
        setId: UUID?,
        setIndex: UInt?,
        restOrder: UInt?
    ): Int? {
        fun firstMatching(predicate: (WorkoutState) -> Boolean): Int? {
            val index = allStates.indexOfFirst(predicate)
            return index.takeIf { it >= 0 }
        }

        val normalizedStateType = stateType.uppercase()

        val exactMatch = when (normalizedStateType) {
            "SET" -> firstMatching { state ->
                state is WorkoutState.Set &&
                    (setId == null || state.set.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }

            "REST" -> firstMatching { state ->
                state is WorkoutState.Rest &&
                    (setId == null || state.set.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (restOrder == null || state.order == restOrder)
            }

            "CALIBRATION_LOAD" -> firstMatching { state ->
                state is WorkoutState.CalibrationLoadSelection &&
                    (setId == null || state.calibrationSet.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }

            "CALIBRATION_RIR" -> firstMatching { state ->
                state is WorkoutState.CalibrationRIRSelection &&
                    (setId == null || state.calibrationSet.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }

            else -> null
        }

        if (exactMatch != null) return exactMatch

        // Calibration fallback when calibration selection states are missing in regenerated sequence.
        if (normalizedStateType == "CALIBRATION_LOAD" || normalizedStateType == "CALIBRATION_RIR") {
            val calibrationSetFallback = firstMatching { state ->
                state is WorkoutState.Set &&
                    state.isCalibrationSet &&
                    (setId == null || state.set.id == setId) &&
                    (exerciseId == null || state.exerciseId == exerciseId) &&
                    (setIndex == null || state.setIndex == setIndex)
            }
            if (calibrationSetFallback != null) return calibrationSetFallback
        }

        val genericSetFallback = firstMatching { state ->
            state is WorkoutState.Set &&
                (exerciseId == null || state.exerciseId == exerciseId) &&
                (setIndex == null || state.setIndex == setIndex)
        }
        if (genericSetFallback != null) return genericSetFallback

        return firstMatching { _ -> true }
    }

    private suspend fun resetWorkoutRuntimeState() {
        stateMachine = null
        setStates.clear()
        weightsByEquipment.clear()
        executedSetStore.clear()
        heartBeatHistory.clear()
        startWorkoutTime = null
        currentWorkoutHistory = null
        _isPaused.value = false
    }

    private suspend fun prepareWorkoutForStart(foundWorkout: Workout) {
        _selectedWorkout.value = foundWorkout
        rebuildScreenState()
        loadWorkoutHistory()
        preProcessExercises()
        generateProgressions()
        applyProgressions()

        val workoutSequence = generateWorkoutStates()
        val machine = initializeStateMachine(workoutSequence, 0)
        populateNextStateForRest(machine)
        stateMachine = machine
        populateNextStateSets()
        markSessionReady()
        triggerWorkoutNotification()
    }

    open fun startWorkout() {
        val selectedWorkoutIdSnapshot = _selectedWorkoutId.value
        val workoutsSnapshot = _workouts.value
        launchMain {
            withContext(dispatchers.io) {
                try {
                    _enableWorkoutNotificationFlow.value = null
                    _currentScreenDimmingState.value = false

                    enterPreparingPhase()

                    resetWorkoutRuntimeState()

                    val foundWorkout = workoutSessionOrchestrator.selectWorkout(
                        workouts = workoutsSnapshot,
                        selectedWorkoutId = selectedWorkoutIdSnapshot
                    )
                    
                    if (foundWorkout == null) {
                        Log.e("WorkoutViewModel", "Workout not found for id: $selectedWorkoutIdSnapshot")
                        markSessionReady()
                        return@withContext
                    }

                    prepareWorkoutForStart(foundWorkout)
                } catch (e: Exception) {
                    Log.e("WorkoutViewModel", "Error in startWorkout()", e)
                    val currentState = _workoutState.value
                    if (currentState is WorkoutState.Preparing) {
                        markSessionReady()
                    }
                    throw e
                }
            }
        }
    }

    protected suspend fun restoreExecutedSets() {
        workoutSessionLifecycleService.restoreExecutedSetsForWorkoutHistory(
            workout = selectedWorkout.value,
            workoutHistoryId = currentWorkoutHistory?.id ?: _workoutRecord?.workoutHistoryId
        )
    }

    protected suspend fun loadWorkoutHistory() {
        val loadedHistory = workoutSessionLifecycleService.loadWorkoutHistory(selectedWorkout.value)
        latestSetHistoriesByExerciseId.clear()
        latestSetHistoriesByExerciseId.putAll(loadedHistory.latestSetHistoriesByExerciseId)
        latestSetHistoryMap.clear()
        loadedHistory.latestSetHistoryByExerciseAndSetId.forEach { (key, value) ->
            latestSetHistoryMap[SetKey(key.first, key.second)] = value
        }
    }

    open fun registerHeartBeat(heartBeat: Int) {
        heartBeatHistory.add(heartBeat)
    }

    internal fun updateWorkout(currentExercise: Exercise, updatedExercise: Exercise) {
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
        val refreshRequest = workoutRefreshService.createRefreshRequest(
            isRefreshing = _isRefreshing.value,
            currentState = _workoutState.value,
            oldHistory = stateMachine?.history ?: emptyList()
        ) ?: return

        launchIO {
            _isRefreshing.value = true

            try {
                val workoutSequence = generateWorkoutStates()
            
                // Initialize new state machine starting at the beginning
                var newMachine = initializeStateMachine(workoutSequence, 0)
                // Populate nextState for Rest states
                populateNextStateForRest(newMachine)
            
                val targetIndex = workoutRefreshService.findTargetIndex(
                    allStates = newMachine.allStates,
                    request = refreshRequest
                )
            
                // If we found the target, reposition and advance one step
                if (targetIndex >= 0) {
                    newMachine = workoutRefreshService.repositionToNextStateAfterTarget(
                        workoutSequence = workoutSequence,
                        targetIndex = targetIndex
                    )
                }
            
                stateMachine = newMachine
                // Populate setStates from allWorkoutStates
                populateNextStateSets()
                updateStateFlowsFromMachine()

                rebuildScreenState()
            } finally {
                _isRefreshing.value = false
            }
        }
    }

    open fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context? = null,
        forceNotSend: Boolean = false,
        onEnd: suspend () -> Unit = {}
    ) {
        launchIO {
            storeSetDataJob?.join()
            val snapshot = workoutPersistenceCoordinator.capturePushWorkoutDataSnapshot(
                startWorkoutTime = startWorkoutTime,
                selectedWorkout = selectedWorkout.value,
                currentWorkoutHistory = currentWorkoutHistory,
                heartBeatRecords = heartBeatHistory.toList(),
                progressionByExerciseId = exerciseProgressionByExerciseId.toMap()
            ) ?: return@launchIO
            val workoutHistoryForThisPush = workoutPersistenceCoordinator.pushWorkoutData(
                snapshot = snapshot,
                isDone = isDone,
                updateWorkoutStore = ::updateWorkoutStore
            )
            withContext(dispatchers.main) {
                currentWorkoutHistory = workoutHistoryForThisPush
            }
            onEnd()
        }
    }

    fun storeSetData() {
        val snapshot = workoutPersistenceCoordinator.captureSetHistorySnapshot(
            currentState = _workoutState.value,
            exercisesById = exercisesById
        )
        val previousJob = storeSetDataJob
        val newJob = launchIO {
            previousJob?.join()
            snapshot?.let { workoutPersistenceCoordinator.upsertSetHistorySnapshot(it) }
        }
        storeSetDataJob = newJob
        newJob.invokeOnCompletion {
            if (storeSetDataJob === newJob) {
                storeSetDataJob = null
            }
        }
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

    protected suspend fun generateWorkoutStates() : List<WorkoutStateSequenceItem> {
        val workoutComponents = selectedWorkout.value.workoutComponents.filter { it.enabled }
        val sequence = mutableListOf<WorkoutStateSequenceItem>()
        val processedExercises = mutableListOf<Exercise>()

        for ((index, workoutComponent) in workoutComponents.withIndex()) {
            when (workoutComponent) {
                is Exercise -> {
                    val warmupContext = WarmupContextBuilder.build(
                        exercise = workoutComponent,
                        priorExercises = processedExercises,
                        isSupersetFollowUp = false
                    )
                    val childItems = addStatesFromExercise(workoutComponent, processedExercises, warmupContext)
                    val exerciseContainer = WorkoutStateContainer.ExerciseState(
                        exerciseId = workoutComponent.id,
                        childItems = childItems.toMutableList()
                    )
                    sequence.add(WorkoutStateSequenceItem.Container(exerciseContainer))
                    processedExercises.add(workoutComponent)
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

                    sequence.add(WorkoutStateSequenceItem.RestBetweenExercises(restState))
                }

                is Superset -> {
                    val superset = workoutComponent
                    val queues = superset.exercises.mapIndexed { supersetIndex, exercise ->
                        val priorExercises = if (supersetIndex == 0) {
                            processedExercises
                        } else {
                            processedExercises + superset.exercises.take(supersetIndex)
                        }
                        val warmupContext = WarmupContextBuilder.build(
                            exercise = exercise,
                            priorExercises = priorExercises,
                            isSupersetFollowUp = supersetIndex > 0
                        )
                        addStatesFromExercise(exercise, priorExercises, warmupContext).flatMap { item ->
                            when (item) {
                                is ExerciseChildItem.Normal -> listOf(item.state)
                                is ExerciseChildItem.CalibrationExecutionBlock -> item.childStates
                                is ExerciseChildItem.LoadSelectionBlock -> item.childStates
                                is ExerciseChildItem.UnilateralSetBlock -> item.childStates
                            }
                        }.toMutableList()
                    }
                    val cleaned = workoutSupersetAssemblyService.assembleSupersetChildStates(
                        superset = superset,
                        queues = queues
                    )

                    val supersetContainer = WorkoutStateContainer.SupersetState(
                        supersetId = superset.id,
                        childStates = cleaned.toMutableList()
                    )
                    sequence.add(WorkoutStateSequenceItem.Container(supersetContainer))
                    processedExercises.addAll(superset.exercises)
                }
            }
        }

        return sequence.toList()
    }

    /**
     * Populates setStates from allWorkoutStates (extracted from state machine).
     * This maintains the setStates list for backward compatibility.
     */
    internal fun populateNextStateSets() {
        setStates.clear()
        // Use allStates which is already flattened and in correct order
        allWorkoutStates.filterIsInstance<WorkoutState.Set>().forEach { 
            setStates.addLast(it) 
        }
    }

    /**
     * Populates nextState for all Rest states in the sequence.
     * For each Rest at index i, sets rest.nextState = allStates.getOrNull(i + 1).
     */
    internal fun populateNextStateForRest(machine: WorkoutStateMachine) {
        WorkoutStateEditor.populateRestNextState(machine)
    }

    /**
     * Returns the first WorkoutState.Set in the flattened state list after the current index.
     * Used when the next state is not a Set (e.g. CalibrationLoadSelection) but a component needs a Set.
     */
    fun getFirstSetStateAfterCurrent(): WorkoutState.Set? {
        val machine = stateMachine ?: return null
        val idx = machine.currentIndex
        val states = machine.allStates
        return states.drop(idx + 1).firstOrNull { it is WorkoutState.Set } as? WorkoutState.Set
    }

    protected fun getPlateChangeResults(
        exercise: Exercise,
        exerciseSets: List<Set>,
        equipment: WeightLoadedEquipment?,
        initialSetup: List<Double> = emptyList()
    ): List<PlateCalculator.Companion.PlateChangeResult> {
        val plateChangeResults = mutableListOf<PlateCalculator.Companion.PlateChangeResult>()

        if (equipment is Barbell && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)) {
            val relativeBodyWeight = if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
            } else {
                0.0
            }

            val setWeights = mutableListOf<Double>()
            for (set in exerciseSets) {
                when (set) {
                    is WeightSet -> {
                        setWeights.add(set.weight)
                    }
                    is BodyWeightSet -> {
                        val totalWeight = relativeBodyWeight + set.additionalWeight
                        setWeights.add(totalWeight)
                    }
                    else -> {
                        // Skip non-weight sets
                    }
                }
            }

            if (setWeights.isNotEmpty()) {
                val plateWeights = equipment.availablePlates.map { it.weight }.toList()

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
        }

        return plateChangeResults
    }

    internal fun getPlateChangeResults(
        weights: List<Double>,
        equipment: Barbell,
        initialSetup: List<Double> = emptyList()
    ): List<PlateCalculator.Companion.PlateChangeResult> {
        val plateWeights = equipment.availablePlates.map { it.weight }.toList()

        return try {
            PlateCalculator.calculatePlateChanges(
                plateWeights,
                weights,
                equipment.barWeight,
                initialSetup,
            )
        } catch (e: Exception) {
            Log.e("PlatesCalculator", "Error calculating plate changes", e)
            emptyList()
        }
    }

    /**
     * Returns [ExerciseChildItem] list for an exercise: calibration blocks when [Exercise.requiresLoadCalibration],
     * otherwise [ExerciseChildItem.Normal] for each state.
     */
    protected suspend fun addStatesFromExercise(
        exercise: Exercise,
        priorExercises: List<Exercise> = emptyList(),
        warmupContext: WarmupContext? = null
    ): List<ExerciseChildItem> {
        if (exercise.sets.isEmpty()) return emptyList()

        val childItems = mutableListOf<ExerciseChildItem>()
        val hasCalibration = exercise.requiresLoadCalibration &&
            (exercise.exerciseType == ExerciseType.WEIGHT ||
                (exercise.exerciseType == ExerciseType.BODY_WEIGHT && exercise.equipmentId != null))
        val loadBlockStates = mutableListOf<WorkoutState>()
        val calibrationExecBlockStates = mutableListOf<WorkoutState>()

        val progressionData =
            if (exerciseProgressionByExerciseId.containsKey(exercise.id)) exerciseProgressionByExerciseId[exercise.id] else null

        val exerciseProgression = progressionData?.first
        val progressionState = progressionData?.second

        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }

        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exercise.id)
        val exerciseAllSets = workoutSetPreparationService.prepareExerciseSets(
            exercise = exercise,
            priorExercises = priorExercises,
            equipment = equipment,
            bodyWeightKg = bodyWeight.value,
            getAvailableTotals = ::getCachedAvailableTotals
        )

        val plateChangeResults = getPlateChangeResults(exercise, exerciseAllSets, equipment)

        val weightSets = exerciseAllSets.filterIsInstance<WeightSet>()

        val isUnilateralExercise = workoutSetStateFactory.isUnilateralExercise(exercise)

        for ((index, set) in exerciseAllSets.withIndex()) {
            if (set is RestSet) {
                val restState = WorkoutState.Rest(
                    set = set,
                    order = index.toUInt(),
                    currentSetDataState = mutableStateOf(initializeSetData(set)),
                    exerciseId = exercise.id
                )
                childItems.add(ExerciseChildItem.Normal(restState))
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
                    if (exercise.doNotStoreHistory) null else latestSetHistoryMap[SetKey(exercise.id, set.id)]

                if (historySet != null) {
                    val historySetData = historySet.setData
                    if (isSetDataValid(set, historySetData) && exerciseProgression == null) {
                        currentSetData = copySetData(historySetData)
                        previousSetData = historySet.setData
                    }
                }

                val weightSetIndex = weightSets.indexOf(set)
                val plateChangeResult = plateChangeResults.getOrNull(weightSetIndex)

                val isWarmupSet = workoutSetStateFactory.isWarmupSet(set)
                val isCalibrationSet = workoutSetStateFactory.isCalibrationSet(set)
                
                // For calibration sets: add CalibrationLoadSelection only.
                // Calibration execution state is inserted after load confirmation (and after generated warmups).
                if (isCalibrationSet && hasCalibration) {
                    loadBlockStates.add(
                        workoutSetStateFactory.buildCalibrationLoadSelectionState(
                            exercise = exercise,
                            set = set,
                            setIndex = index,
                            previousSetData = previousSetData,
                            currentSetData = currentSetData,
                            bodyWeightKg = bodyWeight.value,
                            isUnilateral = isUnilateralExercise,
                            getEquipmentById = ::getEquipmentById
                        )
                    )
                } else if (isCalibrationSet) {
                    // Calibration set but no hasCalibration (shouldn't happen) – treat as normal
                    val setState = workoutSetStateFactory.buildWorkoutSetState(
                        exercise = exercise,
                        set = set,
                        setIndex = index,
                        previousSetData = previousSetData,
                        currentSetData = currentSetData,
                        historySet = historySet,
                        plateChangeResult = plateChangeResult,
                        exerciseInfo = exerciseInfo,
                        progressionState = progressionState,
                        isWarmupSet = isWarmupSet,
                        bodyWeightKg = bodyWeight.value,
                        isUnilateral = isUnilateralExercise,
                        isCalibrationSet = true,
                        getEquipmentById = ::getEquipmentById
                    )
                    childItems.add(ExerciseChildItem.Normal(setState))
                } else {
                    val setState = workoutSetStateFactory.buildWorkoutSetState(
                        exercise = exercise,
                        set = set,
                        setIndex = index,
                        previousSetData = previousSetData,
                        currentSetData = currentSetData,
                        historySet = historySet,
                        plateChangeResult = plateChangeResult,
                        exerciseInfo = exerciseInfo,
                        progressionState = progressionState,
                        isWarmupSet = isWarmupSet,
                        bodyWeightKg = bodyWeight.value,
                        isUnilateral = isUnilateralExercise,
                        isCalibrationSet = false,
                        getEquipmentById = ::getEquipmentById
                    )

                    val unilateralBlock = if (!isWarmupSet && isUnilateralExercise) {
                        workoutSetStateFactory.buildUnilateralSetBlock(exercise, setState, index)
                    } else {
                        null
                    }

                    if (unilateralBlock != null) {
                        childItems.add(unilateralBlock)
                    } else {
                        childItems.add(ExerciseChildItem.Normal(setState))
                    }
                }
            }
        }

        return if (hasCalibration && loadBlockStates.isNotEmpty()) {
            listOf(
                ExerciseChildItem.LoadSelectionBlock(loadBlockStates),
                ExerciseChildItem.CalibrationExecutionBlock(calibrationExecBlockStates)
            ) + childItems
        } else {
            childItems
        }
    }

    fun setWorkoutStart() {
        val startTime = LocalDateTime.now()
        startWorkoutTime = startTime
        if (stateMachine != null) updateStateFlowsFromMachine()
        rebuildScreenState()
        // Persist a baseline unfinished workout immediately so process-death recovery
        // can discover an incomplete workout before the first completed set.
        pushAndStoreWorkoutData(isDone = false, context = null, forceNotSend = true)
    }

    /**
     * Checks if advancing would exit the machine sequence and transition to Completed UI state.
     */
    fun isNextStateCompleted(): Boolean {
        val machine = stateMachine ?: return false
        return machine.currentIndex >= machine.allStates.lastIndex
    }

    open fun goToNextState() {
        val machine = stateMachine ?: return
        if (_workoutState.value is WorkoutState.Preparing) {
            updateStateFlowsFromMachine()
            return
        }
        if (_workoutState.value is WorkoutState.Completed) return
        if (machine.currentIndex >= machine.allStates.lastIndex) {
            val workoutStart = startWorkoutTime ?: LocalDateTime.now().also { startWorkoutTime = it }
            val completedState = WorkoutState.Completed(workoutStart).apply {
                endWorkoutTime = LocalDateTime.now()
            }
            _workoutState.value = completedState
            _nextWorkoutState.value = null
            _sessionPhase.value = WorkoutSessionPhase.COMPLETED
            _isHistoryEmpty.value = machine.isHistoryEmpty
            workoutTimerService.unregisterAll()
            rebuildScreenState()
            return
        }

        stateMachine = machine.next()
        updateStateFlowsFromMachine()
    }

    fun completeCalibrationSet() {
        val machine = stateMachine ?: return
        val currentState = machine.currentState as? WorkoutState.Set ?: return
        
        if (currentState.isCalibrationSet) {
            // Create CalibrationRIRSelection state
            val calibrationRIRState = WorkoutState.CalibrationRIRSelection(
                exerciseId = currentState.exerciseId,
                calibrationSet = currentState.set,
                setIndex = currentState.setIndex,
                currentSetDataState = currentState.currentSetDataState,
                equipment = currentState.equipment,
                lowerBoundMaxHRPercent = currentState.lowerBoundMaxHRPercent,
                upperBoundMaxHRPercent = currentState.upperBoundMaxHRPercent,
                currentBodyWeight = currentState.currentBodyWeight
            )
            // Create Rest state after calibration RIR (session-only, 60s like warmup rest)
            val restSet = RestSet(UUID.randomUUID(), 60)
            val restState = WorkoutState.Rest(
                set = restSet,
                order = currentState.setIndex + 1u,
                currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                exerciseId = currentState.exerciseId
            )
            
            // Insert CalibrationRIRSelection and Rest after current Set state in the container
            val currentFlatIndex = machine.currentIndex
            val position = machine.getContainerAndChildIndex(currentFlatIndex)
            if (position == null) return
            val updatedMachine = when (position) {
                is ContainerPosition.Exercise -> machine.updateExerciseChildItem(position) { childItem ->
                    if (childItem is ExerciseChildItem.CalibrationExecutionBlock) {
                        val newChildStates = childItem.childStates.toMutableList()
                        newChildStates.add(position.indexWithinChildItem + 1, calibrationRIRState)
                        newChildStates.add(position.indexWithinChildItem + 2, restState)
                        ExerciseChildItem.CalibrationExecutionBlock(newChildStates)
                    } else {
                        childItem
                    }
                }
                is ContainerPosition.Superset -> machine.updateSupersetChildStates(position) { updatedChildStates ->
                    updatedChildStates.add(position.childIndex + 1, calibrationRIRState)
                    updatedChildStates.add(position.childIndex + 2, restState)
                    updatedChildStates
                }
            }
            populateNextStateForRest(updatedMachine)
            stateMachine = updatedMachine.withCurrentIndex(currentFlatIndex + 1)
            updateStateFlowsFromMachine()
        }
    }

    fun undo() {
        val machine = stateMachine ?: return
        if (machine.isAtStart) return
        
        stateMachine = machine.undo()
        updateStateFlowsFromMachine()
    }

    /**
     * Navigates to the previous non-Rest state by searching backwards through allStates.
     * Skips Rest states (including RestBetweenExercises and intra-set rest).
     * Useful when going back from CalibrationLoadSelection to skip any Rest states
     * and go directly to the previous Set or other non-Rest state.
     */
    fun goToPreviousNonRestState() {
        val machine = stateMachine ?: return
        if (machine.isAtStart) return

        val targetIndex = machine.findPreviousNonRestIndex() ?: return

        // Navigate directly to the target state using state machine
        stateMachine = machine.withCurrentIndex(targetIndex)
        updateStateFlowsFromMachine()
    }

    suspend fun recalculatePlatesForCurrentAndSubsequentSets(newWeight: Double) {
        // Skip if weight hasn't changed (within epsilon for floating point)
        val lastRecalculatedWeight = lastPlateRecalculationWeight
        if (lastRecalculatedWeight != null && kotlin.math.abs(newWeight - lastRecalculatedWeight) < 0.01) {
            return
        }
        lastPlateRecalculationWeight = newWeight

        _isPlateRecalculationInProgress.value = true
        try {
            val machine = stateMachine ?: return
            val currentState = machine.currentState as? WorkoutState.Set ?: return

            // Verify it's a WeightSet or BodyWeightSet
            val isWeightSet = currentState.set is WeightSet
            val isBodyWeightSet = currentState.set is BodyWeightSet
            if (!isWeightSet && !isBodyWeightSet) return

            val exercise = exercisesById[currentState.exerciseId] ?: return
            val equipment = currentState.equipment

            // Verify equipment is Barbell
            if (equipment !is Barbell) return

            // Get all remaining sets in the exercise (current + subsequent) from machine.allStates
            val currentIndex = machine.currentIndex
            val remainingStates = WorkoutStateQueries.remainingSetStatesForExercise(
                machine = machine,
                fromIndexInclusive = currentIndex,
                exerciseId = currentState.exerciseId
            )

            if (remainingStates.isEmpty()) return

            // Build list of weights for plate calculation
            val relativeBodyWeight = if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
            } else {
                0.0
            }

            val weights = mutableListOf<Double>()
            for ((index, state) in remainingStates.withIndex()) {
                if (index == 0) {
                    // Current set: use newWeight (already the total weight)
                    weights.add(newWeight)
                } else {
                    // Subsequent sets: calculate total weight from their Set objects
                    when (val set = state.set) {
                        is WeightSet -> {
                            weights.add(set.weight)
                        }
                        is BodyWeightSet -> {
                            val totalWeight = relativeBodyWeight + set.additionalWeight
                            weights.add(totalWeight)
                        }
                        else -> {
                            // Skip non-weight sets
                        }
                    }
                }
            }

            if (weights.isEmpty()) return

            // Determine initialPlates: the currentPlates from the previous set's plateChangeResult, or empty if this is the first set
            val initialPlates = WorkoutStateQueries.previousSetStateForExercise(
                machine = machine,
                beforeIndexExclusive = currentIndex,
                exerciseId = currentState.exerciseId
            )?.plateChangeResult?.currentPlates ?: emptyList()

            // Recalculate plateChangeResults using the new overload (on background thread)
            val plateChangeResults = withContext(dispatchers.default) {
                getPlateChangeResults(weights, equipment, initialPlates)
            }

            if (plateChangeResults.size != remainingStates.size) {
                Log.e("WorkoutViewModel", "Plate change results count (${plateChangeResults.size}) doesn't match remaining states count (${remainingStates.size})")
                return
            }

            // Update plateChangeResult in the sequence (on main thread)
            withContext(dispatchers.main) {
                val replacements = remainingStates.mapIndexed { idx, state ->
                    (WorkoutStateQueries.stateSetId(state) ?: state.set.id) to
                        state.copy(plateChangeResult = plateChangeResults[idx])
                }.toMap()
                stateMachine = WorkoutStateEditor.replaceBySetId(machine, replacements)
                updateStateFlowsFromMachine()
            }
        } finally {
            _isPlateRecalculationInProgress.value = false
        }
    }

    /**
     * Recalculates plateChangeResult for all work sets of an exercise starting at a given state index.
     * Used after calibration RIR when the current state is Rest (so [recalculatePlatesForCurrentAndSubsequentSets] would exit early).
     * Does not change the current state index.
     */
    internal suspend fun recalculatePlatesForExerciseFromIndex(
        exerciseId: UUID,
        firstWorkSetStateIndex: Int,
        weights: List<Double>,
        equipment: Barbell
    ) {
        val machine = stateMachine ?: return
        val allStates = machine.allStates
        if (firstWorkSetStateIndex < 0 || firstWorkSetStateIndex >= allStates.size) return

        val remainingStates = WorkoutStateQueries.remainingSetStatesForExercise(
            machine = machine,
            fromIndexInclusive = firstWorkSetStateIndex,
            exerciseId = exerciseId
        )

        if (remainingStates.isEmpty() || weights.size != remainingStates.size) {
            if (weights.size != remainingStates.size) {
                Log.e("WorkoutViewModel", "recalculatePlatesForExerciseFromIndex: weights count (${weights.size}) doesn't match work set states count (${remainingStates.size})")
            }
            return
        }

        val initialPlates = WorkoutStateQueries.previousSetStateForExercise(
            machine = machine,
            beforeIndexExclusive = firstWorkSetStateIndex,
            exerciseId = exerciseId
        )?.plateChangeResult?.currentPlates ?: emptyList()

        val plateChangeResults = withContext(dispatchers.default) {
            getPlateChangeResults(weights, equipment, initialPlates)
        }

        if (plateChangeResults.size != remainingStates.size) {
            Log.e("WorkoutViewModel", "Plate change results count (${plateChangeResults.size}) doesn't match remaining states count (${remainingStates.size})")
            return
        }

        withContext(dispatchers.main) {
            val replacements = remainingStates.mapIndexed { idx, state ->
                (WorkoutStateQueries.stateSetId(state) ?: state.set.id) to
                    state.copy(plateChangeResult = plateChangeResults[idx])
            }.toMap()
            stateMachine = WorkoutStateEditor.replaceBySetId(machine, replacements)
            updateStateFlowsFromMachine()
        }
    }

    fun schedulePlateRecalculation(newWeight: Double) {
        launchDefault {
            plateRecalculationDebouncer.schedule {
                recalculatePlatesForCurrentAndSubsequentSets(newWeight)
            }
        }
    }

    suspend fun flushPlateRecalculation() {
        plateRecalculationDebouncer.flush()
    }
    
    private fun updateCurrentStateInMachine(updatedState: WorkoutState) {
        val machine = stateMachine ?: return
        stateMachine = machine.updateCurrentState(updatedState)
        updateStateFlowsFromMachine()
    }

    /**
     * Navigates to the previous Set state, skipping Rest states and calibration states.
     * 
     * Handles calibration states correctly:
     * - When called from CalibrationLoadSelection, finds the previous non-calibration Set state
     * - Skips calibration sets (isCalibrationSet) to avoid re-entering calibration flow
     * - Calibration context will be cleared when navigating to a non-calibration Set
     */
    fun goToPreviousSet() {
        val machine = stateMachine ?: return
        if (machine.isAtStart) return

        val currentState = machine.currentState
        
        // Return early if current state is Preparing or Completed
        if (currentState is WorkoutState.Preparing || currentState is WorkoutState.Completed) {
            return
        }

        // Get current set.id (works for Set, Rest, and calibration states)
        val currentSetId = WorkoutStateQueries.stateSetId(currentState) ?: return

        // Search backwards through allStates to find the previous Set state with different set.id
        // Start from currentIndex - 1 (the state before current) and go backwards to 0
        // Skip calibration states (CalibrationLoadSelection, CalibrationRIRSelection) and Rest states
        val targetIndex = machine.findPreviousSetIndex(excludedSetId = currentSetId) ?: return

        // Navigate directly to the target Set state
        stateMachine = machine.withCurrentIndex(targetIndex)
        updateStateFlowsFromMachine()

        // Clean up executedSetsHistory: remove all entries that correspond to sets after the target Set
        launchIO {
            // Get all setIds that come after the target Set in allStates
            val setIdsToRemove = WorkoutStateQueries.collectSetIdsAfterIndex(machine, targetIndex)

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
        val currentExerciseId = WorkoutStateQueries.stateExerciseId(currentState) ?: return

        // Skip until we find a Set with different exerciseId or Completed state
        val newMachine = machine.skipUntil { state ->
            (state is WorkoutState.Set && WorkoutStateQueries.stateExerciseId(state) != currentExerciseId) ||
            state is WorkoutState.Completed
        }

        stateMachine = newMachine
        updateStateFlowsFromMachine()
    }
}
