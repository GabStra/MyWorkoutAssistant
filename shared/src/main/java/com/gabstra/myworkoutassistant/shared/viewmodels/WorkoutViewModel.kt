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
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.utils.PlateauDetectionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.WarmupContext
import com.gabstra.myworkoutassistant.shared.utils.WarmupContextBuilder
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlanner
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
import kotlin.coroutines.EmptyCoroutineContext
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

    /**
     * Synchronously flush timer state to database.
     * Should be called on app lifecycle events (onPause/onStop) to ensure timer state is persisted.
     * This prevents loss of timer progress when app is closed mid-timer.
     */
    suspend fun flushTimerState() {
        withContext(dispatchers.io) {
            // Wait for any pending storeSetData job to complete
            storeSetDataJob?.join()
            // Force save current timer state
            storeSetDataInternal()
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
     * Initializes the state machine from a list of workout states.
     * Filters out trailing Rest states and adds Completed state.
     * 
     * @param workoutStates The list of workout states to initialize from
     * @param startIndex The index to start at (defaults to 0)
     */
    /**
     * Applies executed set data to states in the sequence.
     */
    private fun applyExecutedSetDataToSequence(
        sequence: List<WorkoutStateSequenceItem>,
        executedSetsHistorySnapshot: List<SetHistory>
    ): List<WorkoutStateSequenceItem> {
        return sequence.map { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            val flatStates = container.flattenChildItems()
                            val updatedFlat = flatStates.map { state ->
                                when (state) {
                                    is WorkoutState.Set -> {
                                        val setHistory = executedSetsHistorySnapshot.firstOrNull { sh ->
                                            matchesSetHistory(sh, state.set.id, state.setIndex, state.exerciseId)
                                        }
                                        if (setHistory != null) state.currentSetData = setHistory.setData
                                        state
                                    }
                                    is WorkoutState.Rest -> {
                                        val setHistory = executedSetsHistorySnapshot.firstOrNull { sh ->
                                            matchesSetHistory(sh, state.set.id, state.order, state.exerciseId)
                                        }
                                        if (setHistory != null) state.currentSetData = setHistory.setData
                                        state
                                    }
                                    else -> state
                                }
                            }
                            val updatedChildItems = rebuildExerciseChildItemsFromFlat(container.childItems, updatedFlat)
                            WorkoutStateSequenceItem.Container(
                                container.copy(childItems = updatedChildItems)
                            )
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val updatedChildStates = container.childStates.map { state ->
                                when (state) {
                                    is WorkoutState.Set -> {
                                        val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                                            matchesSetHistory(
                                                setHistory,
                                                state.set.id,
                                                state.setIndex,
                                                state.exerciseId
                                            )
                                        }
                                        if (setHistory != null) {
                                            state.currentSetData = setHistory.setData
                                        }
                                        state
                                    }
                                    is WorkoutState.Rest -> {
                                        val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                                            matchesSetHistory(
                                                setHistory,
                                                state.set.id,
                                                state.order,
                                                state.exerciseId
                                            )
                                        }
                                        if (setHistory != null) {
                                            state.currentSetData = setHistory.setData
                                        }
                                        state
                                    }
                                    else -> state
                                }
                            }.toMutableList()
                            WorkoutStateSequenceItem.Container(
                                container.copy(childStates = updatedChildStates)
                            )
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    val setHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                        matchesSetHistory(
                            setHistory,
                            item.rest.set.id,
                            item.rest.order,
                            item.rest.exerciseId
                        )
                    }
                    if (setHistory != null) {
                        item.rest.currentSetData = setHistory.setData
                    }
                    item
                }
            }
        }
    }

    private fun initializeStateMachine(sequence: List<WorkoutStateSequenceItem>, startIndex: Int = 0): WorkoutStateMachine {
        // Flatten to check for trailing Rest and add Completed state
        val allStates = sequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> container.flattenChildItems()
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
            }
        }

        val filteredStates = allStates.toMutableList()
        
        // Remove trailing Rest state if present
        if (filteredStates.isNotEmpty() && filteredStates.last() is WorkoutState.Rest) {
            filteredStates.removeAt(filteredStates.size - 1)
        }
        
        // Add Completed state if startWorkoutTime is set
        val finalSequence = if (startWorkoutTime != null) {
            // Find the last container and add Completed to its childStates, or create a new container
            val updatedSequence = sequence.toMutableList()
            if (updatedSequence.isNotEmpty()) {
                val lastItem = updatedSequence.last()
                when (lastItem) {
                    is WorkoutStateSequenceItem.Container -> {
                        when (val container = lastItem.container) {
                            is WorkoutStateContainer.ExerciseState -> {
                                val updatedChildItems = container.childItems.toMutableList()
                                updatedChildItems.add(ExerciseChildItem.Normal(WorkoutState.Completed(startWorkoutTime!!)))
                                updatedSequence[updatedSequence.size - 1] = WorkoutStateSequenceItem.Container(
                                    container.copy(childItems = updatedChildItems)
                                )
                            }
                            is WorkoutStateContainer.SupersetState -> {
                                val updatedChildStates = container.childStates.toMutableList()
                                updatedChildStates.add(WorkoutState.Completed(startWorkoutTime!!))
                                updatedSequence[updatedSequence.size - 1] = WorkoutStateSequenceItem.Container(
                                    container.copy(childStates = updatedChildStates)
                                )
                            }
                        }
                    }
                    is WorkoutStateSequenceItem.RestBetweenExercises -> {
                        val dummyExerciseId = UUID.randomUUID()
                        val completedContainer = WorkoutStateContainer.ExerciseState(
                            exerciseId = dummyExerciseId,
                            childItems = mutableListOf(ExerciseChildItem.Normal(WorkoutState.Completed(startWorkoutTime!!)))
                        )
                        updatedSequence.add(WorkoutStateSequenceItem.Container(completedContainer))
                    }
                }
            } else {
                val dummyExerciseId = UUID.randomUUID()
                val completedContainer = WorkoutStateContainer.ExerciseState(
                    exerciseId = dummyExerciseId,
                    childItems = mutableListOf(ExerciseChildItem.Normal(WorkoutState.Completed(startWorkoutTime!!)))
                )
                updatedSequence.add(WorkoutStateSequenceItem.Container(completedContainer))
            }
            updatedSequence
        } else {
            sequence
        }
        
        // Calculate adjusted startIndex
        val finalAllStates = finalSequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> container.flattenChildItems()
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
            }
        }

        val adjustedStartIndex = if (startWorkoutTime != null && startIndex >= finalAllStates.size - 1) {
            finalAllStates.size - 1
        } else {
            startIndex.coerceIn(0, finalAllStates.size - 1)
        }
        
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
        return when (state) {
            is WorkoutState.CalibrationLoadSelection -> CalibrationContext(
                exerciseId = state.exerciseId,
                calibrationSetId = state.calibrationSet.id,
                phase = CalibrationPhase.LOAD_SELECTION,
                calibrationSetExecutionStateIndex = null
            )
            is WorkoutState.Set -> if (state.isCalibrationSet) {
                CalibrationContext(
                    exerciseId = state.exerciseId,
                    calibrationSetId = state.set.id,
                    phase = CalibrationPhase.EXECUTING,
                    calibrationSetExecutionStateIndex = machine.currentIndex
                )
            } else null
            is WorkoutState.CalibrationRIRSelection -> CalibrationContext(
                exerciseId = state.exerciseId,
                calibrationSetId = state.calibrationSet.id,
                phase = CalibrationPhase.RIR_SELECTION,
                calibrationSetExecutionStateIndex = machine.currentIndex - 1
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

    /**
     * Rebuilds the WorkoutScreenState from current ViewModel fields.
     * Call this whenever any UI-observable field changes.
     * Only emits if the new state differs from the current state to prevent unnecessary recompositions.
     */
    protected open fun rebuildScreenState() {
        val newState = WorkoutScreenState(
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
        launchIO {
            when {
                _workoutRecord == null && currentWorkoutHistory != null -> {
                    _workoutRecord = WorkoutRecord(
                        id = UUID.randomUUID(),
                        workoutId = selectedWorkout.value.id,
                        exerciseId = exerciseId,
                        setIndex = setIndex,
                        workoutHistoryId = currentWorkoutHistory!!.id
                    )
                    workoutRecordDao.insert(_workoutRecord!!)
                    _hasWorkoutRecord.value = true
                }
                _workoutRecord != null -> {
                    _workoutRecord = _workoutRecord!!.copy(
                        exerciseId = exerciseId,
                        setIndex = setIndex,
                    )
                    workoutRecordDao.insert(_workoutRecord!!)
                    _hasWorkoutRecord.value = true
                }
                else -> {
                    // First set of first exercise: no history/record created yet, nothing to persist
                }
            }
            rebuildScreenState()
        }
    }

    fun deleteWorkoutRecord() {
        launchIO {
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
            // Capture workoutStore value at the start to avoid race conditions
            val currentWorkoutStore = workoutStore
            val incompleteHistories = workoutHistoryDao.getAllUnfinishedWorkoutHistories(isDone = false)

            // Group by workoutId and get the most recent one for each workout
            val groupedByWorkoutId = incompleteHistories
                .groupBy { it.workoutId }
                .mapValues { (_, histories) ->
                    histories.maxByOrNull { it.startTime } ?: histories.first()
                }
            
            // Map to IncompleteWorkout with workout name
            groupedByWorkoutId.values.mapNotNull { workoutHistory ->
                val workout = currentWorkoutStore.workouts.find { it.id == workoutHistory.workoutId }
                    ?: currentWorkoutStore.workouts.find { it.globalId == workoutHistory.globalId }

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
                        
                        // Match by setId, order, and exerciseId when available (not just setId)
                        val matchingSetHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                            matchesSetHistory(
                                setHistory,
                                state.set.id,
                                state.setIndex,
                                state.exerciseId
                            )
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
                        // Match by setId, order, and exerciseId when available (not just setId)
                        val matchingSetHistory = executedSetsHistorySnapshot.firstOrNull { setHistory ->
                            matchesSetHistory(
                                setHistory,
                                state.set.id,
                                state.order,
                                state.exerciseId
                            )
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
        launchMain {
            withContext(dispatchers.io) {
                _enableWorkoutNotificationFlow.value = null
                _currentScreenDimmingState.value = false

                val preparingState = WorkoutState.Preparing(dataLoaded = false)

                _workoutState.value = preparingState
                stateMachine = null
                setStates.clear()
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
                val workoutSequence = generateWorkoutStates()

                // Take a snapshot of executedSetsHistory (immutable from StateFlow)
                val executedSetsHistorySnapshot = executedSetStore.executedSets.value

                // Apply executed set data to states in containers
                val updatedSequence = applyExecutedSetDataToSequence(workoutSequence, executedSetsHistorySnapshot)

                // Flatten to find resumption index
                val allStates = updatedSequence.flatMap { item ->
                    when (item) {
                        is WorkoutStateSequenceItem.Container -> {
                            when (val container = item.container) {
                                is WorkoutStateContainer.ExerciseState -> container.flattenChildItems()
                                is WorkoutStateContainer.SupersetState -> container.childStates
                            }
                        }
                        is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
                    }
                }

                // Remove trailing Rest state if present
                val filteredStates = allStates.toMutableList()
                if (filteredStates.isNotEmpty() && filteredStates.last() is WorkoutState.Rest) {
                    filteredStates.removeAt(filteredStates.size - 1)
                }

                // Find the resumption index using WorkoutRecord (primary) or SetHistory (fallback)
                val resumptionIndex = findResumptionIndex(filteredStates, executedSetsHistorySnapshot)
                
                // Populate nextState for Rest states
                populateNextStateForRest(updatedSequence)
                
                // Populate setStates from allWorkoutStates
                populateNextStateSets()
                
                // Initialize state machine with sequence at the correct resumption index
                stateMachine = initializeStateMachine(updatedSequence, resumptionIndex)
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

    /**
     * Returns the ordered list of workout states associated with the exercise (from the exercise's
     * container in the state machine: ExerciseState.childStates or filtered SupersetState.childStates).
     * Includes Set, CalibrationLoadSelection, and CalibrationRIRSelection in schedule order.
     */
    fun getStatesForExercise(exerciseId: UUID): List<WorkoutState> {
        return stateMachine?.getStatesForExercise(exerciseId) ?: emptyList()
    }

    /**
     * Returns the total number of logical sets for an exercise, from the state machine.
     * Counts Set, CalibrationLoadSelection, and CalibrationRIRSelection (unilateral counts once).
     */
    fun getTotalSetCountForExercise(exerciseId: UUID): Int {
        val exerciseStates = stateMachine?.getStatesForExercise(exerciseId) ?: return 0
        val orderedSetIds = mutableListOf<UUID>()
        for (state in exerciseStates) {
            val setId = when (state) {
                is WorkoutState.Set -> state.set.id
                is WorkoutState.CalibrationLoadSelection -> state.calibrationSet.id
                is WorkoutState.CalibrationRIRSelection -> state.calibrationSet.id
                else -> continue
            }
            if (setId !in orderedSetIds) {
                orderedSetIds.add(setId)
            }
        }
        return orderedSetIds.size
    }

    /**
     * Returns (currentSetIndex1Based, totalSetCount) for the given exercise and current state.
     * Uses the state machine's exercise states as source of truth (not exercise.sets, which can be updated).
     * Handles WorkoutState.Set, CalibrationLoadSelection, and CalibrationRIRSelection.
     * Returns null when the current state does not represent a set (e.g. Rest) or is not for this exercise.
     */
    fun getSetCounterForExercise(exerciseId: UUID, currentState: WorkoutState): Pair<Int, Int>? {
        val total = getTotalSetCountForExercise(exerciseId)
        if (total == 0) return null
        val exerciseStates = stateMachine?.getStatesForExercise(exerciseId) ?: return null
        val orderedSetIds = mutableListOf<UUID>()
        for (state in exerciseStates) {
            val setId = when (state) {
                is WorkoutState.Set -> state.set.id
                is WorkoutState.CalibrationLoadSelection -> state.calibrationSet.id
                is WorkoutState.CalibrationRIRSelection -> state.calibrationSet.id
                else -> continue
            }
            if (setId !in orderedSetIds) {
                orderedSetIds.add(setId)
            }
        }
        val currentSetId = when (currentState) {
            is WorkoutState.Set -> if (currentState.exerciseId == exerciseId) currentState.set.id else null
            is WorkoutState.CalibrationLoadSelection -> if (currentState.exerciseId == exerciseId) currentState.calibrationSet.id else null
            is WorkoutState.CalibrationRIRSelection -> if (currentState.exerciseId == exerciseId) currentState.calibrationSet.id else null
            else -> null
        } ?: return null
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

    /** Rebuilds [ExerciseChildItem] list from flattened updated states (same order/size as [container].flattenChildItems()). */
    internal fun rebuildExerciseChildItemsFromFlat(
        childItems: MutableList<ExerciseChildItem>,
        updatedFlat: List<WorkoutState>
    ): MutableList<ExerciseChildItem> {
        var idx = 0
        return childItems.map { item ->
            when (item) {
                is ExerciseChildItem.Normal -> ExerciseChildItem.Normal(updatedFlat[idx++])
                is ExerciseChildItem.CalibrationExecutionBlock -> {
                    val n = item.childStates.size
                    ExerciseChildItem.CalibrationExecutionBlock(
                        updatedFlat.subList(idx, idx + n).toMutableList()
                    ).also { idx += n }
                }
                is ExerciseChildItem.LoadSelectionBlock -> {
                    val n = item.childStates.size
                    ExerciseChildItem.LoadSelectionBlock(
                        updatedFlat.subList(idx, idx + n).toMutableList()
                    ).also { idx += n }
                }
                is ExerciseChildItem.UnilateralSetBlock -> {
                    val n = item.childStates.size
                    ExerciseChildItem.UnilateralSetBlock(
                        updatedFlat.subList(idx, idx + n).toMutableList()
                    ).also { idx += n }
                }
            }
        }.toMutableList()
    }

    private fun matchesSetHistory(
        setHistory: SetHistory,
        setId: UUID,
        order: UInt,
        exerciseId: UUID?
    ): Boolean {
        if (setHistory.setId != setId || setHistory.order != order) {
            return false
        }

        return setHistory.exerciseId == null ||
            exerciseId == null ||
            setHistory.exerciseId == exerciseId
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
                    // Filter out RestPauseSet and CalibrationSet sets
                    when(val setData = setHistory.setData){
                        is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                        is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                        is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
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
                    val key = SetKey(exercise.id, set.id)
                    latestSetHistoryMap[key]?.let { getNewSetFromSetHistory(it) } ?: set
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

            updateWorkout(exercise,exercise.copy(sets = validSets, requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList()))
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

            val newExercise = exercise.copy(sets = newSets, requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList())
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
                matchesSetHistory(it, set.id, state.setIndex, state.exerciseId)
            }
            
            val now = LocalDateTime.now()
            
            when {
                set is TimedDurationSet -> {
                    val setData = if (setHistory != null && setHistory.setData is TimedDurationSetData) {
                        setHistory.setData as TimedDurationSetData
                    } else {
                        // No SetHistory exists - check if timer was running based on current state
                        // This handles Bug 2: Missing SetHistory Entry for In-Progress Timer
                        val currentSetData = state.currentSetData as? TimedDurationSetData
                        if (currentSetData != null && currentSetData.endTimer < currentSetData.startTimer && currentSetData.endTimer > 0) {
                            Log.d(TAG, "Restoring timer from current state (no SetHistory): endTimer=${currentSetData.endTimer}, startTimer=${currentSetData.startTimer}")
                            currentSetData
                        } else {
                            Log.d(TAG, "No timer state found for TimedDurationSet - timer will start from beginning")
                            return
                        }
                    }
                    
                    // Only restore if timer was running (endTimer < startTimer and endTimer > 0)
                    // This excludes cases where timer finished (endTimer = 0) or never started (endTimer = startTimer)
                    if (setData.endTimer < setData.startTimer && setData.endTimer > 0) {
                        // Calculate elapsed time: startTimer - endTimer
                        val elapsedMillis = setData.startTimer - setData.endTimer
                        
                        // Validate elapsed time is reasonable (not negative, not exceeding startTimer)
                        if (elapsedMillis > 0 && elapsedMillis <= setData.startTimer) {
                            // Restore startTime so that elapsed time matches
                            state.startTime = now.minusNanos((elapsedMillis * 1_000_000L).toLong())
                            Log.d(TAG, "Restored TimedDurationSet timer: elapsed=${elapsedMillis}ms, remaining=${setData.endTimer}ms")
                        } else {
                            Log.w(TAG, "Invalid elapsed time calculated: ${elapsedMillis}ms for timer with startTimer=${setData.startTimer}ms")
                        }
                    } else {
                        Log.d(TAG, "Timer not running or completed: endTimer=${setData.endTimer}, startTimer=${setData.startTimer}")
                    }
                }
                set is EnduranceSet -> {
                    val setData = if (setHistory != null && setHistory.setData is EnduranceSetData) {
                        setHistory.setData as EnduranceSetData
                    } else {
                        // No SetHistory exists - check if timer was running based on current state
                        val currentSetData = state.currentSetData as? EnduranceSetData
                        if (currentSetData != null && currentSetData.endTimer > 0) {
                            Log.d(TAG, "Restoring timer from current state (no SetHistory): endTimer=${currentSetData.endTimer}")
                            currentSetData
                        } else {
                            Log.d(TAG, "No timer state found for EnduranceSet - timer will start from beginning")
                            return
                        }
                    }
                    
                    // Only restore if timer was running (endTimer > 0)
                    if (setData.endTimer > 0 && setData.endTimer <= setData.startTimer) {
                        // Restore startTime so that elapsed time matches endTimer
                        state.startTime = now.minusNanos((setData.endTimer * 1_000_000L).toLong())
                        Log.d(TAG, "Restored EnduranceSet timer: elapsed=${setData.endTimer}ms")
                    } else {
                        Log.d(TAG, "Timer not running or invalid: endTimer=${setData.endTimer}, startTimer=${setData.startTimer}")
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

        launchIO {
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
        launchMain {
            withContext(dispatchers.io) {
                try {
                    _enableWorkoutNotificationFlow.value = null
                    _currentScreenDimmingState.value = false

                    val preparingState = WorkoutState.Preparing(dataLoaded = false)
                    _workoutState.value = preparingState

                    stateMachine = null
                    setStates.clear()
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
                    val workoutSequence = generateWorkoutStates()

                    // Populate nextState for Rest states
                    populateNextStateForRest(workoutSequence)
                    
                    // Initialize state machine (without Completed state - will be added in setWorkoutStart())
                    stateMachine = initializeStateMachine(workoutSequence, 0)
                    
                    // Populate setStates from allWorkoutStates
                    populateNextStateSets()
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
                latestSetHistoryMap[SetKey(exercise.id, setHistoryFound.setId)] = setHistoryFound
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
        launchIO {
            if (_isRefreshing.value || (_workoutState.value !is WorkoutState.Set && _workoutState.value !is WorkoutState.Rest)) return@launchIO

            _isRefreshing.value = true

            val targetSetId = when (_workoutState.value) {
                is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                else -> throw RuntimeException("Invalid state")
            }
            val targetExerciseId = when (_workoutState.value) {
                is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).exerciseId
                is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).exerciseId
                else -> throw RuntimeException("Invalid state")
            }

            fun matchesTargetState(state: WorkoutState): Boolean {
                val setId = when (state) {
                    is WorkoutState.Set -> state.set.id
                    is WorkoutState.Rest -> state.set.id
                    else -> null
                }
                val exerciseId = when (state) {
                    is WorkoutState.Set -> state.exerciseId
                    is WorkoutState.Rest -> state.exerciseId
                    else -> null
                }
                return setId == targetSetId && exerciseId == targetExerciseId
            }

            // Count how many states with this setId were in history before refresh
            val oldHistory = stateMachine?.history ?: emptyList()
            val completedMatchingCount = oldHistory.count { state ->
                matchesTargetState(state)
            }

            val workoutSequence = generateWorkoutStates()
            
            // Populate nextState for Rest states
            populateNextStateForRest(workoutSequence)

            // Initialize new state machine starting at the beginning
            var newMachine = initializeStateMachine(workoutSequence, 0)
            
            // Populate setStates from allWorkoutStates
            populateNextStateSets()
            
            // Find the (completedMatchingCount + 1)th occurrence of targetSetId
            // This corresponds to the state we were at before refresh
            var occurrenceCount = 0
            var targetIndex = -1
            
            for (i in 0 until newMachine.allStates.size) {
                val state = newMachine.allStates[i]
                if (matchesTargetState(state)) {
                    occurrenceCount++
                    if (occurrenceCount == completedMatchingCount + 1) {
                        targetIndex = i
                        break
                    }
                }
            }
            
            // If we found the target, reposition and advance one step
            if (targetIndex >= 0) {
                // Reposition to target index using the sequence we already have
                newMachine = WorkoutStateMachine.fromSequence(workoutSequence, { LocalDateTime.now() }, targetIndex)
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
                            is BodyWeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            is WeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            is RestSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
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
        launchIO {
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
                                is BodyWeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                                is WeightSetData     -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                                is RestSetData       -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
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
                                if (setData.subCategory == SetSubCategory.RestPauseSet || setData.subCategory == SetSubCategory.CalibrationSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            is BodyWeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet || setData.subCategory == SetSubCategory.CalibrationSet) return@mapNotNull null
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
                            is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                            is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                            is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
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

                // Check for completed calibration sets and disable calibration requirement
                var updatedWorkoutComponents = workoutComponents
                for (exercise in exercises) {
                    if (!exercise.requiresLoadCalibration) continue

                    val updatedExercise = exercise.copy(requiresLoadCalibration = false)
                    updatedWorkoutComponents = updateWorkoutComponentsRecursively(
                        updatedWorkoutComponents,
                        exercise,
                        updatedExercise
                    )
                    Log.d(TAG, "Disabled calibration requirement for exercise: ${exercise.name}")
                }

                // Update WorkoutStore with the modified workout components if any changes were made
                if (updatedWorkoutComponents != workoutComponents) {
                    val finalWorkoutStore = newWorkoutStore.copy(workouts = newWorkoutStore.workouts.map {
                        if (it.id == _selectedWorkout.value.id) {
                            it.copy(workoutComponents = updatedWorkoutComponents)
                        } else {
                            it
                        }
                    })

                    updateWorkoutStore(finalWorkoutStore)
                    workoutStoreRepository.saveWorkoutStore(finalWorkoutStore)
                }
            }

            onEnd()
        }
    }

    fun storeSetData() {
        val previousJob = storeSetDataJob
        val newJob = launchIO {
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
            val isCalibrationSet = when(val set = currentState.set) {
                is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                else -> false
            }
            // Allow calibration sets to be stored if they have a calibrationRIR (completed calibration)
            val hasCalibrationRIR = when(val setData = currentState.currentSetData) {
                is WeightSetData -> setData.calibrationRIR != null
                is BodyWeightSetData -> setData.calibrationRIR != null
                else -> false
            }
            // Skip if: doNotStoreHistory, warmup set, or calibration set without RIR (not yet completed)
            if (exercise.doNotStoreHistory || isWarmupSet || (isCalibrationSet && !hasCalibrationRIR)) return
        }

        if(currentState is WorkoutState.Rest && currentState.isIntraSetRest) return

        val newSetHistory = when (currentState) {
            is WorkoutState.Set -> {
                // Use current time as fallback if startTime is null
                val startTime = currentState.startTime ?: LocalDateTime.now()
                
                // Log timer state for debugging (Bug 1 & 3: Track timer persistence)
                val setData = currentState.currentSetData
                if (setData is TimedDurationSetData || setData is EnduranceSetData) {
                    val timerInfo = when (setData) {
                        is TimedDurationSetData -> "TimedDurationSet: startTimer=${setData.startTimer}ms, endTimer=${setData.endTimer}ms, startTime=$startTime"
                        is EnduranceSetData -> "EnduranceSet: startTimer=${setData.startTimer}ms, endTimer=${setData.endTimer}ms, startTime=$startTime"
                        else -> ""
                    }
                    Log.d(TAG, "Storing timer state: $timerInfo")
                }
                
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
            is WorkoutState.Set -> { history ->
                matchesSetHistory(
                    history,
                    currentState.set.id,
                    currentState.setIndex,
                    currentState.exerciseId
                )
            }
            is WorkoutState.Rest -> { history ->
                matchesSetHistory(
                    history,
                    currentState.set.id,
                    currentState.order,
                    currentState.exerciseId
                )
            }
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
    internal fun populateNextStateForRest(sequence: List<WorkoutStateSequenceItem>) {
        val allStates = sequence.flatMap { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> container.flattenChildItems()
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
            }
        }
        for (i in allStates.indices) {
            val currentState = allStates[i]
            if (currentState is WorkoutState.Rest) {
                currentState.nextState = allStates.getOrNull(i + 1)
            }
        }
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
        var seenCalibration = false

        val progressionData =
            if (exerciseProgressionByExerciseId.containsKey(exercise.id)) exerciseProgressionByExerciseId[exercise.id] else null

        val exerciseProgression = progressionData?.first
        val progressionState = progressionData?.second

        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
        val exerciseAllSets = mutableListOf<Set>()

        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exercise.id)

        val exerciseSets = exercise.sets

        // Skip warm up generation if calibration is enabled - warm ups will be generated after load selection
        if(exercise.generateWarmUpSets && !exercise.requiresLoadCalibration && equipment != null && (exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT)){
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
                    exercise = exercise,
                    priorExercises = priorExercises,
                    initialSetup = emptyList(),
                    maxWarmups = 3
                )
            } else {
                WarmupPlanner.buildWarmupSets(
                    availableTotals = availableTotals,
                    workWeight = workWeightTotal,
                    workReps = workReps,
                    exercise = exercise,
                    priorExercises = priorExercises,
                    equipment = equipment,
                    maxWarmups = 3
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

        // Insert calibration set before first work set if required
        if (exercise.requiresLoadCalibration && 
            (exercise.exerciseType == ExerciseType.WEIGHT || 
             (exercise.exerciseType == ExerciseType.BODY_WEIGHT && equipment != null))) {
            
            // Find first work set (not warmup, not rest)
            val firstWorkSetIndex = exerciseAllSets.indexOfFirst { set ->
                when (set) {
                    is RestSet -> false
                    is BodyWeightSet -> set.subCategory == SetSubCategory.WorkSet
                    is WeightSet -> set.subCategory == SetSubCategory.WorkSet
                    else -> false
                }
            }
            
            if (firstWorkSetIndex >= 0) {
                val firstWorkSet = exerciseAllSets[firstWorkSetIndex]
                val calibrationSet = when (firstWorkSet) {
                    is WeightSet -> {
                        WeightSet(
                            id = UUID.randomUUID(),
                            reps = firstWorkSet.reps,
                            weight = firstWorkSet.weight,
                            subCategory = SetSubCategory.CalibrationSet
                        )
                    }
                    is BodyWeightSet -> {
                        BodyWeightSet(
                            id = UUID.randomUUID(),
                            reps = firstWorkSet.reps,
                            additionalWeight = firstWorkSet.additionalWeight,
                            subCategory = SetSubCategory.CalibrationSet
                        )
                    }
                    else -> null
                }
                
                if (calibrationSet != null) {
                    // Insert calibration set before first work set
                    exerciseAllSets.add(firstWorkSetIndex, calibrationSet)
                }
            }
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

                val isWarmupSet = when(set) {
                    is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                    else -> false
                }
                
                val isCalibrationSet = when(set) {
                    is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                    is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                    else -> false
                }

                val isUnilateral = exercise.intraSetRestInSeconds != null && exercise.intraSetRestInSeconds > 0
                
                // For calibration sets: add CalibrationLoadSelection to LoadSelectionBlock and Set(calibration) to CalibrationExecutionBlock
                if (isCalibrationSet && hasCalibration) {
                    val calibrationLoadSelectionState = WorkoutState.CalibrationLoadSelection(
                        exerciseId = exercise.id,
                        calibrationSet = set,
                        setIndex = index.toUInt(),
                        previousSetData = previousSetData,
                        currentSetDataState = mutableStateOf(currentSetData),
                        equipment = exercise.equipmentId?.let { getEquipmentById(it) },
                        lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
                        upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
                        currentBodyWeight = bodyWeight.value,
                        isUnilateral = isUnilateral
                    )
                    loadBlockStates.add(calibrationLoadSelectionState)
                    val calibrationSetState = WorkoutState.Set(
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
                        isWarmupSet = false,
                        exercise.equipmentId?.let { getEquipmentById(it) },
                        isUnilateral = isUnilateral,
                        isCalibrationSet = true
                    )
                    calibrationExecBlockStates.add(calibrationSetState)
                    seenCalibration = true
                } else if (isCalibrationSet) {
                    // Calibration set but no hasCalibration (shouldn't happen) – treat as normal
                    val setState = WorkoutState.Set(
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
                        isUnilateral = isUnilateral,
                        isCalibrationSet = true
                    )
                    childItems.add(ExerciseChildItem.Normal(setState))
                } else {
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
                        isUnilateral = isUnilateral,
                        isCalibrationSet = false
                    )

                    if(!isWarmupSet && isUnilateral){
                        val restDuration = exercise.intraSetRestInSeconds!!
                        val restSet = RestSet(UUID.randomUUID(), restDuration)
                        val restState = WorkoutState.Rest(
                            set = restSet,
                            order = index.toUInt(),
                            currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                            nextState = setState,
                            exerciseId = exercise.id,
                            isIntraSetRest = true
                        )

                        val newSetState = setState.copy(isUnilateral = true, intraSetTotal = 2u, intraSetCounter = 1u)

                        childItems.add(
                            ExerciseChildItem.UnilateralSetBlock(
                                mutableListOf(newSetState, restState, newSetState)
                            )
                        )
                    }else{
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
        
            // Add Completed state to the last container
        val machine = stateMachine
        if (machine != null && !machine.isCompleted) {
            val updatedSequence = machine.stateSequence.toMutableList()
            if (updatedSequence.isNotEmpty()) {
                val lastItem = updatedSequence.last()
                when (lastItem) {
                    is WorkoutStateSequenceItem.Container -> {
                        when (val container = lastItem.container) {
                            is WorkoutStateContainer.ExerciseState -> {
                                val updatedChildItems = container.childItems.toMutableList()
                                updatedChildItems.add(ExerciseChildItem.Normal(WorkoutState.Completed(startWorkoutTime!!)))
                                updatedSequence[updatedSequence.size - 1] = WorkoutStateSequenceItem.Container(
                                    container.copy(childItems = updatedChildItems)
                                )
                            }
                            is WorkoutStateContainer.SupersetState -> {
                                val updatedChildStates = container.childStates.toMutableList()
                                updatedChildStates.add(WorkoutState.Completed(startWorkoutTime!!))
                                updatedSequence[updatedSequence.size - 1] = WorkoutStateSequenceItem.Container(
                                    container.copy(childStates = updatedChildStates)
                                )
                            }
                        }
                    }
                    is WorkoutStateSequenceItem.RestBetweenExercises -> {
                        val dummyExerciseId = UUID.randomUUID()
                        val completedContainer = WorkoutStateContainer.ExerciseState(
                            exerciseId = dummyExerciseId,
                            childItems = mutableListOf(ExerciseChildItem.Normal(WorkoutState.Completed(startWorkoutTime!!)))
                        )
                        updatedSequence.add(WorkoutStateSequenceItem.Container(completedContainer))
                    }
                }
            }
            stateMachine = WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, machine.currentIndex)
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

        val nextState = machine.next()
        stateMachine = nextState
        updateStateFlowsFromMachine()
        
        // Clean up timers when workout completes
        if (nextState.currentState is WorkoutState.Completed) {
            workoutTimerService.unregisterAll()
        }
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
            val updatedSequence = when (position) {
                is ContainerPosition.Exercise -> {
                    machine.stateSequence.mapIndexed { seqIdx, seqItem ->
                        if (seqIdx != position.containerSeqIndex || seqItem !is WorkoutStateSequenceItem.Container) {
                            seqItem
                        } else {
                            val container = seqItem.container
                            if (container is WorkoutStateContainer.ExerciseState) {
                                val childItem = container.childItems.getOrNull(position.childItemIndex)
                                if (childItem is ExerciseChildItem.CalibrationExecutionBlock) {
                                    val newChildStates = childItem.childStates.toMutableList()
                                    newChildStates.add(position.indexWithinChildItem + 1, calibrationRIRState)
                                    newChildStates.add(position.indexWithinChildItem + 2, restState)
                                    val newChildItems = container.childItems.toMutableList()
                                    newChildItems[position.childItemIndex] =
                                        ExerciseChildItem.CalibrationExecutionBlock(newChildStates)
                                    WorkoutStateSequenceItem.Container(
                                        container.copy(childItems = newChildItems)
                                    )
                                } else {
                                    seqItem
                                }
                            } else {
                                seqItem
                            }
                        }
                    }
                }
                is ContainerPosition.Superset -> {
                    machine.stateSequence.mapIndexed { seqIdx, item ->
                        if (seqIdx != position.containerSeqIndex || item !is WorkoutStateSequenceItem.Container) {
                            item
                        } else {
                            val container = item.container
                            if (container is WorkoutStateContainer.SupersetState) {
                                val updatedChildStates = container.childStates.toMutableList()
                                updatedChildStates.add(position.childIndex + 1, calibrationRIRState)
                                updatedChildStates.add(position.childIndex + 2, restState)
                                WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                            } else {
                                item
                            }
                        }
                    }
                }
            }
            populateNextStateForRest(updatedSequence)
            stateMachine = WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, currentFlatIndex + 1)
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

        // Search backwards to find first non-Rest state
        var targetIndex = -1
        for (i in machine.currentIndex - 1 downTo 0) {
            val state = machine.allStates[i]
            if (state !is WorkoutState.Rest) {
                targetIndex = i
                break
            }
        }

        // If no previous non-Rest state found, return early
        if (targetIndex < 0) {
            return
        }

        // Navigate directly to the target state using state machine
        stateMachine = WorkoutStateMachine.fromSequence(machine.stateSequence, { LocalDateTime.now() }, targetIndex)
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
            val remainingStates = machine.allStates.subList(currentIndex, machine.allStates.size)
                .filterIsInstance<WorkoutState.Set>()
                .filter { it.exerciseId == currentState.exerciseId }

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
            val initialPlates = if (currentIndex > 0) {
                // Find the previous set state in the same exercise
                val previousState = machine.allStates.subList(0, currentIndex)
                    .filterIsInstance<WorkoutState.Set>()
                    .filter { it.exerciseId == currentState.exerciseId }
                    .lastOrNull()
                previousState?.plateChangeResult?.currentPlates ?: emptyList()
            } else {
                emptyList()
            }

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
                // Create a map of setId -> plateChangeResult for quick lookup
                val plateChangeMap = remainingStates.mapIndexedNotNull { idx, state ->
                    if (idx < plateChangeResults.size) {
                        state.set.id to plateChangeResults[idx]
                    } else {
                        null
                    }
                }.toMap()
                
                val updatedSequence = machine.stateSequence.map { item ->
                    when (item) {
                        is WorkoutStateSequenceItem.Container -> {
                            when (val container = item.container) {
                                is WorkoutStateContainer.ExerciseState -> {
                                    val flatStates = container.flattenChildItems()
                                    val updatedFlat = flatStates.map { state ->
                                        if (state is WorkoutState.Set && state.exerciseId == currentState.exerciseId) {
                                            val plateChangeResult = plateChangeMap[state.set.id]
                                            if (plateChangeResult != null) state.copy(plateChangeResult = plateChangeResult)
                                            else state
                                        } else state
                                    }
                                    val updatedChildItems = rebuildExerciseChildItemsFromFlat(container.childItems, updatedFlat)
                                    WorkoutStateSequenceItem.Container(container.copy(childItems = updatedChildItems))
                                }
                                is WorkoutStateContainer.SupersetState -> {
                                    val updatedChildStates = container.childStates.map { state ->
                                        if (state is WorkoutState.Set && state.exerciseId == currentState.exerciseId) {
                                            val plateChangeResult = plateChangeMap[state.set.id]
                                            if (plateChangeResult != null) state.copy(plateChangeResult = plateChangeResult)
                                            else state
                                        } else state
                                    }.toMutableList()
                                    WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                                }
                            }
                        }
                        is WorkoutStateSequenceItem.RestBetweenExercises -> item
                    }
                }
                stateMachine = WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, machine.currentIndex)
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

        val remainingStates = allStates.subList(firstWorkSetStateIndex, allStates.size)
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }

        if (remainingStates.isEmpty() || weights.size != remainingStates.size) {
            if (weights.size != remainingStates.size) {
                Log.e("WorkoutViewModel", "recalculatePlatesForExerciseFromIndex: weights count (${weights.size}) doesn't match work set states count (${remainingStates.size})")
            }
            return
        }

        val initialPlates = if (firstWorkSetStateIndex > 0) {
            allStates.subList(0, firstWorkSetStateIndex)
                .filterIsInstance<WorkoutState.Set>()
                .filter { it.exerciseId == exerciseId }
                .lastOrNull()
                ?.plateChangeResult?.currentPlates ?: emptyList()
        } else {
            emptyList()
        }

        val plateChangeResults = withContext(dispatchers.default) {
            getPlateChangeResults(weights, equipment, initialPlates)
        }

        if (plateChangeResults.size != remainingStates.size) {
            Log.e("WorkoutViewModel", "Plate change results count (${plateChangeResults.size}) doesn't match remaining states count (${remainingStates.size})")
            return
        }

        withContext(dispatchers.main) {
            val plateChangeMap = remainingStates.mapIndexedNotNull { idx, state ->
                if (idx < plateChangeResults.size) {
                    state.set.id to plateChangeResults[idx]
                } else null
                }.toMap()

            val updatedSequence = machine.stateSequence.map { item ->
                when (item) {
                    is WorkoutStateSequenceItem.Container -> {
                        when (val container = item.container) {
                            is WorkoutStateContainer.ExerciseState -> {
                                val flatStates = container.flattenChildItems()
                                val updatedFlat = flatStates.map { state ->
                                    if (state is WorkoutState.Set && state.exerciseId == exerciseId) {
                                        val plateChangeResult = plateChangeMap[state.set.id]
                                        if (plateChangeResult != null) state.copy(plateChangeResult = plateChangeResult)
                                        else state
                                    } else state
                                }
                                val updatedChildItems = rebuildExerciseChildItemsFromFlat(container.childItems, updatedFlat)
                                WorkoutStateSequenceItem.Container(container.copy(childItems = updatedChildItems))
                            }
                            is WorkoutStateContainer.SupersetState -> {
                                val updatedChildStates = container.childStates.map { state ->
                                    if (state is WorkoutState.Set && state.exerciseId == exerciseId) {
                                        val plateChangeResult = plateChangeMap[state.set.id]
                                        if (plateChangeResult != null) state.copy(plateChangeResult = plateChangeResult)
                                        else state
                                    } else state
                                }.toMutableList()
                                WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                            }
                        }
                    }
                    is WorkoutStateSequenceItem.RestBetweenExercises -> item
                }
            }
            stateMachine = WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, machine.currentIndex)
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
        val currentIndex = machine.currentIndex
        
        if (currentIndex < 0 || currentIndex >= machine.allStates.size) return
        
        // Find and update the state in the sequence
        var currentFlatPos = 0
        val updatedSequence = machine.stateSequence.map { item ->
            when (item) {
                is WorkoutStateSequenceItem.Container -> {
                    when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> {
                            val flatStates = container.flattenChildItems()
                            val updatedFlat = flatStates.mapIndexed { idx, state ->
                                if (currentFlatPos + idx == currentIndex) updatedState else state
                            }
                            currentFlatPos += flatStates.size
                            val updatedChildItems = rebuildExerciseChildItemsFromFlat(container.childItems, updatedFlat)
                            WorkoutStateSequenceItem.Container(container.copy(childItems = updatedChildItems))
                        }
                        is WorkoutStateContainer.SupersetState -> {
                            val updatedChildStates = container.childStates.mapIndexed { idx, state ->
                                if (currentFlatPos + idx == currentIndex) updatedState else state
                            }.toMutableList()
                            currentFlatPos += container.childStates.size
                            WorkoutStateSequenceItem.Container(container.copy(childStates = updatedChildStates))
                        }
                    }
                }
                is WorkoutStateSequenceItem.RestBetweenExercises -> {
                    val result = if (currentFlatPos == currentIndex) {
                        WorkoutStateSequenceItem.RestBetweenExercises(updatedState as WorkoutState.Rest)
                    } else {
                        item
                    }
                    currentFlatPos++
                    result
                }
            }
        }
        
        stateMachine = WorkoutStateMachine.fromSequence(updatedSequence, { LocalDateTime.now() }, currentIndex)
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
        val currentSetId = when (currentState) {
            is WorkoutState.Set -> currentState.set.id
            is WorkoutState.Rest -> currentState.set.id
            is WorkoutState.CalibrationLoadSelection -> currentState.calibrationSet.id
            is WorkoutState.CalibrationRIRSelection -> currentState.calibrationSet.id
            else -> return
        }

        // Search backwards through allStates to find the previous Set state with different set.id
        // Start from currentIndex - 1 (the state before current) and go backwards to 0
        // Skip calibration states (CalibrationLoadSelection, CalibrationRIRSelection) and Rest states
        var targetIndex = -1
        for (i in machine.currentIndex - 1 downTo 0) {
            val state = machine.allStates[i]
            if (state is WorkoutState.Set) {
                // Found a Set state - check if it has a different set.id
                // Also skip calibration sets (isCalibrationSet) to avoid going back to calibration flow
                if (state.set.id != currentSetId && !state.isCalibrationSet) {
                    targetIndex = i
                    break
                }
            }
            // Skip Rest states and calibration states, continue searching
        }

        // If no previous Set state found, return early
        if (targetIndex < 0) {
            return
        }

        // Navigate directly to the target Set state
        stateMachine = WorkoutStateMachine.fromSequence(machine.stateSequence, { LocalDateTime.now() }, targetIndex)
        updateStateFlowsFromMachine()

        // Clean up executedSetsHistory: remove all entries that correspond to sets after the target Set
        launchIO {
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
