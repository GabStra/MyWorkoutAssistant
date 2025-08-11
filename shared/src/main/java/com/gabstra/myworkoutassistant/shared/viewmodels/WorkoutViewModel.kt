package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import android.util.Log
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
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
import com.gabstra.myworkoutassistant.shared.calculateOneRepMax
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.getNewSet
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
import com.gabstra.myworkoutassistant.shared.repsForTargetRIR
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper.ExerciseProgression
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper.ExerciseSet
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper.createSet
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper.recalculateExerciseFatigue
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.Calendar
import java.util.LinkedList
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue
import kotlin.math.floor

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

open class WorkoutViewModel : ViewModel() {
    var workoutStore by mutableStateOf(
        WorkoutStore(
            workouts = emptyList(),
            polarDeviceId = null,
            birthDateYear = 0,
            weightKg = 0.0,
            equipments = emptyList(),
            progressionPercentageAmount = 0.0,
        )
    )

    fun getEquipmentById(id: UUID): WeightLoadedEquipment? {
        return workoutStore.equipments.find { it.id == id }
    }

    private val _isPaused = mutableStateOf(false) // Private mutable state
    open val isPaused: State<Boolean> = _isPaused // Public read-only State access

    fun pauseWorkout() {
        _isPaused.value = true
    }

    fun resumeWorkout() {
        _isPaused.value = false
    }

    private val _workouts = MutableStateFlow<List<Workout>>(emptyList())
    val workouts = _workouts.asStateFlow()

    private var _userAge = mutableIntStateOf(0)
    val userAge: State<Int> = _userAge

    private var _bodyWeight = mutableStateOf(0.0)
    val bodyWeight: State<Double> = _bodyWeight

    private var _backupProgress = mutableStateOf(0f)
    val backupProgress: State<Float> = _backupProgress

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

    protected lateinit var workoutStoreRepository: WorkoutStoreRepository

    private val _workoutState =
        MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()

    private val _nextWorkoutState =
        MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val nextWorkoutState = _nextWorkoutState.asStateFlow()

    public val executedSetsHistory: MutableList<SetHistory> = mutableListOf()

    protected val heartBeatHistory: ConcurrentLinkedQueue<Int> = ConcurrentLinkedQueue()

    protected val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    protected val workoutStateHistory: MutableList<WorkoutState> = mutableListOf()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    protected val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    public val latestSetHistoriesByExerciseId: MutableMap<UUID, List<SetHistory>> = mutableMapOf()

    public val latestSetHistoryMap: MutableMap<UUID, SetHistory> = mutableMapOf()

    protected val weightsByEquipment: MutableMap<WeightLoadedEquipment, kotlin.collections.Set<Double>> =
        mutableMapOf()

    fun getWeightByEquipment(equipment: WeightLoadedEquipment?): kotlin.collections.Set<Double> {
        if (equipment == null) return emptySet()
        return weightsByEquipment[equipment] ?: emptySet()
    }

    val exerciseProgressionByExerciseId: MutableMap<UUID, Pair<VolumeDistributionHelper.ExerciseProgression?, Boolean>> =
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

    private val _isResuming = MutableStateFlow<Boolean>(false)
    val isResuming = _isResuming.asStateFlow()

    private val _isRefreshing = MutableStateFlow<Boolean>(false)
    val isRefreshing = _isRefreshing.asStateFlow()

    private val _hasWorkoutRecord = MutableStateFlow<Boolean>(false)
    val hasWorkoutRecord = _hasWorkoutRecord.asStateFlow()

    private val _hasExercises = MutableStateFlow<Boolean>(false)
    val hasExercises = _hasExercises.asStateFlow()

    private val _isSkipDialogOpen = MutableStateFlow<Boolean>(false)

    open val isCustomDialogOpen = _isSkipDialogOpen.asStateFlow()

    private val _enableWorkoutNotificationFlow = MutableStateFlow<String?>(null)
    val enableWorkoutNotificationFlow = _enableWorkoutNotificationFlow.asStateFlow()

    fun triggerWorkoutNotification() {
        _enableWorkoutNotificationFlow.value = System.currentTimeMillis().toString()
    }

    // Setter method to open dialog
    fun openCustomDialog() {
        _isSkipDialogOpen.value = true
    }

    // Setter method to close dialog
    fun closeCustomDialog() {
        _isSkipDialogOpen.value = false
    }


    fun setWorkout(workout: Workout) {
        _selectedWorkout.value = workout;

        _hasExercises.value =
            selectedWorkout.value.workoutComponents.filter { it.enabled }.isNotEmpty()

        initializeExercisesMaps(workout)
        getWorkoutRecord(workout)
    }

    fun resetAll() {
        resetWorkoutStore()
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                workoutHistoryDao.deleteAll()
                setHistoryDao.deleteAll()
                exerciseInfoDao.deleteAll()
                workoutRecordDao.deleteAll()
                workoutScheduleDao.deleteAll()
            }
        }
    }

    protected open fun getWorkoutRecord(workout: Workout) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                _workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                _hasWorkoutRecord.value = _workoutRecord != null
            }
        }
    }

    fun upsertWorkoutRecord(exerciseId : UUID,setIndex: UInt) {
        viewModelScope.launch(Dispatchers.IO) {
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
        }
    }

    fun deleteWorkoutRecord() {
        viewModelScope.launch(Dispatchers.IO) {
            _workoutRecord?.let {
                workoutRecordDao.deleteById(it.id)
                _workoutRecord = null
                _hasWorkoutRecord.value = false
            }
        }
    }

    open fun resumeWorkoutFromRecord(onEnd: suspend () -> Unit = {}) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                _enableWorkoutNotificationFlow.value = null

                val preparingState = WorkoutState.Preparing(dataLoaded = false)
                _workoutState.value = preparingState
                workoutStateQueue.clear()
                workoutStateHistory.clear()
                _isHistoryEmpty.value = workoutStateHistory.isEmpty()
                setStates.clear()
                allWorkoutStates.clear()
                weightsByEquipment.clear()

                currentWorkoutHistory =
                    workoutHistoryDao.getWorkoutHistoryById(_workoutRecord!!.workoutHistoryId)
                heartBeatHistory.addAll(currentWorkoutHistory!!.heartBeatRecords)
                startWorkoutTime = currentWorkoutHistory!!.startTime

                restoreExecutedSets()
                loadWorkoutHistory()
                generateProgressions()
                applyProgressions()
                val workoutStates = generateWorkoutStates()

                workoutStates.forEachIndexed { index, it ->
                    if (index == workoutStates.lastIndex && it is WorkoutState.Rest) {
                        return@forEachIndexed
                    }

                    if(it is WorkoutState.Set){
                        val setHistory = executedSetsHistory.firstOrNull { setHistory -> setHistory.setId == it.set.id }
                        if(setHistory != null){
                            it.currentSetData = setHistory.setData
                        }
                    }

                    if(it is WorkoutState.Rest){
                        val setHistory = executedSetsHistory.firstOrNull { setHistory -> setHistory.setId == it.set.id }
                        if(setHistory != null){
                            it.currentSetData = setHistory.setData
                        }
                    }

                    workoutStateQueue.addLast(it)
                    allWorkoutStates.add(it)
                    if(it is WorkoutState.Set){
                        setStates.addLast(it)
                    }
                }

                workoutStateQueue.addLast(WorkoutState.Completed(startWorkoutTime!!))
                preparingState.dataLoaded = true
                triggerWorkoutNotification()
                onEnd()
            }
        }
    }

    public fun getAllExerciseWorkoutStates(exerciseId: UUID): List<WorkoutState.Set> {
        return allWorkoutStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }
    }
    public fun getAllExecutedSetsByExerciseId(exerciseId: UUID): List<SetHistory> {
        return executedSetsHistory.filter { it.exerciseId == exerciseId }
    }

    public fun getAllSetHistoriesByExerciseId(exerciseId: UUID): List<SetHistory> {
        return latestSetHistoriesByExerciseId[exerciseId] ?: emptyList()
    }

    private fun applyProgressions() {
        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        exercises.forEach { exercise ->
            if (exercise.doNotStoreHistory || !exerciseProgressionByExerciseId.containsKey(exercise.id)) return@forEach

            var currentExercise = exercise
            val exerciseProgression = exerciseProgressionByExerciseId[currentExercise.id]!!.first

            if (exerciseProgression != null) {
                val distributedSets = exerciseProgression.sets
                val newSets = mutableListOf<Set>()

                val exerciseSets = currentExercise.sets.filter { it !is RestSet }
                val restSets = currentExercise.sets.filterIsInstance<RestSet>()

                for ((index, setInfo) in distributedSets.withIndex()) {
                    if (index > 0) {
                        val previousRestSet = restSets.getOrNull(index - 1)

                        var newRestSet = RestSet(UUID.randomUUID(), 90, false)

                        if (previousRestSet != null) {
                            newRestSet = newRestSet.copy(id = previousRestSet.id)
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
        }
    }

    protected suspend fun generateProgressions() {
        exerciseProgressionByExerciseId.clear()

        fun getProgressionSetsByExerciseId(exercises: List<Exercise>, bodyWeight: Double): Map<UUID, List<ExerciseSet>> {
            return exercises.associate { exercise ->
                val exerciseSets = exercise.sets.filter { it !is RestSet }

                if (exerciseSets.isEmpty()) {
                    return@associate exercise.id to emptyList()
                }

                // 2. Calculate the average 1RM from all performance sets
                var oneRepMax = exerciseSets.map {
                    when (it) {
                        is BodyWeightSet -> {
                            requireNotNull(exercise.bodyWeightPercentage) { "BodyWeightPercentage must be set for BodyWeightSet." }
                            val relativeBodyWeight = bodyWeight * (exercise.bodyWeightPercentage!! / 100)
                            val weight = it.getWeight(relativeBodyWeight)
                            calculateOneRepMax(weight, it.reps)
                        }

                        is WeightSet -> calculateOneRepMax(it.weight, it.reps)
                        else -> 0.0
                    }
                }.average()


                if (oneRepMax.isNaN() || oneRepMax <= 0) {
                    return@associate exercise.id to emptyList()
                }


                var setsForProgression = exerciseSets.map { it ->
                    when (it) {
                        is BodyWeightSet -> {
                            val relativeBodyWeight = bodyWeight * (exercise.bodyWeightPercentage!! / 100)
                            val weight = it.getWeight(relativeBodyWeight)
                            createSet(weight, it.reps, oneRepMax)
                        }

                        is WeightSet -> {
                            createSet(it.weight, it.reps, oneRepMax)
                        }
                        else -> throw IllegalStateException("Unknown set type encountered after filtering.")
                    }
                }

                setsForProgression = recalculateExerciseFatigue(setsForProgression)

                exercise.id to setsForProgression
            }
        }

        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        val exercisesWithEquipments = exercises.filter { it.enabled && it.equipmentId != null }

        exercisesWithEquipments.map { exercise ->
            val equipment =
                exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }

            if (equipment != null && !weightsByEquipment.containsKey(equipment)) {
                val possibleCombinations = equipment.getWeightsCombinations()
                weightsByEquipment[equipment] = possibleCombinations
            }
        }

        val validExercises = exercises.filter { it -> it.enabled && it.enableProgression && !it.doNotStoreHistory }
            .filter { it.exerciseType == ExerciseType.WEIGHT || it.exerciseType == ExerciseType.BODY_WEIGHT  }

        val progressionSetsByExerciseId = getProgressionSetsByExerciseId(validExercises, bodyWeight.value)

        val fatigueBaseline = progressionSetsByExerciseId
            .values
            .flatten()
            .sumOf { it.fatigue }

        val fatigueBudget = fatigueBaseline * (1 + workoutStore.progressionPercentageAmount/100)
        val fatigueSurplus = fatigueBudget - fatigueBaseline
        
        Log.d("WorkoutViewModel", "Fatigue Baseline: ${fatigueBaseline.round(2)} - Fatigue Budget: ${fatigueBudget.round(2)} - Progression Percentage Amount: ${workoutStore.progressionPercentageAmount.round(2)}%")
        // Process exercises sequentially
        validExercises.forEach { exercise ->

            val setsForProgression = progressionSetsByExerciseId[exercise.id] ?: emptyList()
            if(setsForProgression.isEmpty()) return@forEach

            val totalFatigue = setsForProgression.sumOf { it.fatigue }
            val exerciseWeight = totalFatigue / fatigueBaseline
            val fatigueDeltaProgression = fatigueSurplus * exerciseWeight
            val targetFatigue = totalFatigue + fatigueDeltaProgression

            val result = processExercise(exercise,setsForProgression,targetFatigue)
            result?.let { (exerciseId, progression) ->
                exerciseProgressionByExerciseId[exerciseId] = progression
            }
        }
    }

    // Helper function to process a single exercise
    private suspend fun processExercise(
        exercise: Exercise,
        setsForProgression: List<ExerciseSet>,
        targetFatigue: Double
    ): Pair<UUID, Pair<ExerciseProgression?, Boolean>>? {
        val exerciseSets = exercise.sets.filter { it !is RestSet }

        var oneRepMax = exerciseSets.map {
            when (it) {
                is BodyWeightSet -> {
                    val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    calculateOneRepMax(it.getWeight(relativeBodyWeight), it.reps)
                }

                is WeightSet -> calculateOneRepMax(it.weight, it.reps)
                else -> 0.0
            }
        }.average()

        val repsRange = IntRange(
                exercise.minReps,
                exercise.maxReps
            )

        val exerciseVolume = setsForProgression.sumOf { it.volume }
        val currentFatigue = setsForProgression.sumOf { it.fatigue }

        val shouldDeload = false // exerciseInfo != null && exerciseInfo.sessionFailedCounter >= 2u //( || exerciseInfo.successfulSessionCounter >= 7u)

        val availableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> exercise.equipmentId?.let { getWeightByEquipment(getEquipmentById(it)) }
                ?: emptySet()

            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    getWeightByEquipment(getEquipmentById(it))
                        .map { value -> relativeBodyWeight + value }.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }

            else -> throw IllegalArgumentException("Unknown exercise type")
        }

        if(exercise.exerciseType == ExerciseType.BODY_WEIGHT){
            val relativeBodyWeight =
                bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)

            Log.d(
                "WorkoutViewModel",
                "${exercise.name} (${exercise.exerciseType}) Relative BodyWeight: ${relativeBodyWeight} - 1RM ${
                    String.format(
                        "%.2f",
                        oneRepMax
                    ).replace(",", ".")
                }"
            )

        }else{
            Log.d(
                "WorkoutViewModel",
                "${exercise.name} (${exercise.exerciseType}) - 1RM ${
                    String.format(
                        "%.2f",
                        oneRepMax
                    ).replace(",", ".")
                }"
            )
        }

        val oldSets = exerciseSets.map { set ->
            when (set) {
                is BodyWeightSet -> {
                    val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    set.getWeight(relativeBodyWeight)

                    "${set.getWeight(relativeBodyWeight) - relativeBodyWeight} kg x ${set.reps}"
                }
                is WeightSet -> {
                    "${set.weight} kg x ${set.reps}"
                }
                else -> throw IllegalArgumentException("Unknown set type")
            }
        }

        val oldFatigue = setsForProgression.sumOf { it.fatigue }
        Log.d("WorkoutViewModel", "Old sets: ${oldSets.joinToString(", ")} - Fatigue: ${oldFatigue.round(2)}")

        var exerciseProgression: ExerciseProgression? = null

        if (shouldDeload) {
            Log.d("WorkoutViewModel", "Deloading ${exercise.name}")
            //TODO: Implement deloading
        } else {
            exerciseProgression = VolumeDistributionHelper.getClosestToTargetFatigue(
                previousSets = setsForProgression,
                oneRepMax = oneRepMax,
                availableWeights = availableWeights,
                repsRange = repsRange,
                targetFatigue = targetFatigue
            )
        }

        if (exerciseProgression != null) {
            val newSets = exerciseProgression.sets.mapIndexed { index, set ->
                if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    "${set.weight - relativeBodyWeight} kg x ${set.reps}"
                } else {
                    "${set.weight} kg x ${set.reps}"
                }
            }

            val newFatigue = exerciseProgression.sets.sumOf { it.fatigue }
            Log.d("WorkoutViewModel", "New sets: ${newSets.joinToString(", ")} - Fatigue: ${newFatigue.round(2)}")
            
            val progressIncrease = ((exerciseProgression.newVolume - exerciseProgression.previousVolume) / exerciseProgression.previousVolume) * 100

            val fatigueIncrease = ((exerciseProgression.newFatigue - exerciseProgression.previousFatigue) / exerciseProgression.previousFatigue) * 100


            Log.d(
                "WorkoutViewModel",
                "Volume: ${exerciseProgression.previousVolume.round(2)} kg -> ${exerciseProgression.newVolume .round(2)} kg (${if(progressIncrease>0) "+" else ""}${progressIncrease.round(2)}%)"
            )

            Log.d(
                "WorkoutViewModel",
                "Fatigue: ${exerciseProgression.previousFatigue.round(2)} -> ${exerciseProgression.newFatigue.round(2)} (${if(fatigueIncrease>0) "+" else ""}${fatigueIncrease.round(2)}%)"
            )
        } else {
            Log.d("WorkoutViewModel", "Failed to find progression for ${exercise.name}")
        }

        return exercise.id to Pair(exerciseProgression, shouldDeload)
    }

    fun resumeLastState() {
        if (_workoutRecord == null) return

        fun isCurrentStateTheTargetResumeSet(): Boolean {
            val currentWorkoutState = _workoutState.value

            return currentWorkoutState is WorkoutState.Set &&
                    currentWorkoutState.exerciseId == _workoutRecord!!.exerciseId &&
                    currentWorkoutState.setIndex == _workoutRecord!!.setIndex
        }

        if (isCurrentStateTheTargetResumeSet()) {
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _isResuming.value = true
            while (_workoutState.value !is WorkoutState.Completed) {
                goToNextState()

                if (isCurrentStateTheTargetResumeSet()){
                    break
                }
            }


            delay(2000)
            _isResuming.value = false
        }
    }

    open fun startWorkout() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                _enableWorkoutNotificationFlow.value = null

                val preparingState = WorkoutState.Preparing(dataLoaded = false)
                _workoutState.value = preparingState

                workoutStateQueue.clear()
                workoutStateHistory.clear()
                _isHistoryEmpty.value = workoutStateHistory.isEmpty()
                setStates.clear()
                allWorkoutStates.clear()
                weightsByEquipment.clear()
                executedSetsHistory.clear()
                heartBeatHistory.clear()
                startWorkoutTime = null
                currentWorkoutHistory = null

                loadWorkoutHistory()
                generateProgressions()
                applyProgressions()
                val workoutStates = generateWorkoutStates()

                workoutStates.forEachIndexed { index, it ->
                    if (index == workoutStates.lastIndex && it is WorkoutState.Rest) {
                        return@forEachIndexed
                    }
                    workoutStateQueue.addLast(it)
                    allWorkoutStates.add(it)
                    if(it is WorkoutState.Set){
                        setStates.addLast(it)
                    }
                }

                preparingState.dataLoaded = true
                triggerWorkoutNotification()
            }
        }
    }

    protected suspend fun restoreExecutedSets() {
        if (_workoutRecord == null) return;
        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        executedSetsHistory.clear()
        exercises.filter { !it.doNotStoreHistory }.forEach { exercise ->
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                _workoutRecord!!.workoutHistoryId,
                exercise.id
            )

            executedSetsHistory.addAll(setHistories);
        }
    }

    protected suspend fun loadWorkoutHistory() {
        val workoutHistories = workoutHistoryDao
            .getAllWorkoutHistories()
            .filter { it.globalId == selectedWorkout.value.globalId && it.isDone }
            .sortedByDescending { it.date }

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

        val neverCalledWorkoutHistories =
            workoutHistories.filterIndexed { index, _ -> index !in calledIndexes }

        neverCalledWorkoutHistories.forEach {
            workoutHistoryDao.deleteById(it.id)
        }
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
        val newRestSet = RestSet(UUID.randomUUID(), 20, true)
        newSets.add(currentSetIndex + 1, newRestSet)
        val newSet = when (val new = getNewSet(currentState.set)) {
            is BodyWeightSet -> new.copy(reps = 3)
            is WeightSet -> new.copy(reps = 3)
            else -> throw IllegalArgumentException("Unknown set type")
        }
        newSets.add(currentSetIndex + 2, newSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise, updatedExercise)

        RefreshAndGoToNextState()
    }

    protected fun RefreshAndGoToNextState() {
        viewModelScope.launch(Dispatchers.IO) {
            if (_isRefreshing.value || (_workoutState.value !is WorkoutState.Set && _workoutState.value !is WorkoutState.Rest)) return@launch

            _isRefreshing.value = true

            workoutStateQueue.clear()
            workoutStateHistory.clear()
            _isHistoryEmpty.value = workoutStateHistory.isEmpty()
            setStates.clear()

            generateWorkoutStates()
            workoutStateQueue.addLast(WorkoutState.Completed(startWorkoutTime!!))

            val targetSetId = when (_workoutState.value) {
                is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                else -> throw RuntimeException("Invalid state")
            }

            _workoutState.value = workoutStateQueue.pollFirst()!!

            while (_workoutState.value !is WorkoutState.Completed) {
                val currentSetId = when (_workoutState.value) {
                    is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                    is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                    else -> throw RuntimeException("Invalid state")
                }

                if (currentSetId == targetSetId) {
                    break
                }

                goToNextState()
            }

            if (_workoutState.value !is WorkoutState.Completed) {
                goToNextState()
            }

            _isRefreshing.value = false
        }
    }

    open fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context? = null,
        forceNotSend: Boolean = false,
        onEnd: suspend () -> Unit = {}
    ) {
        viewModelScope.launch(Dispatchers.IO) {
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

            val newExecutedSetsHistory = executedSetsHistory.map {
                it.copy(workoutHistoryId = currentWorkoutHistory!!.id)
            }
            executedSetsHistory.clear()
            executedSetsHistory.addAll(newExecutedSetsHistory)

            workoutHistoryDao.insertWithVersionCheck(currentWorkoutHistory!!)
            setHistoryDao.insertAllWithVersionCheck(*executedSetsHistory.toTypedArray())

            val exerciseInfos = mutableListOf<ExerciseInfo>()

            if (isDone) {
                val exerciseHistoriesByExerciseId = executedSetsHistory.groupBy { it.exerciseId }

                val exerciseHistoriesSetsByExerciseId =
                    exerciseHistoriesByExerciseId.filter { it.value.any { it.setData is BodyWeightSetData || it.setData is WeightSetData } }

                exerciseHistoriesSetsByExerciseId.forEach { it ->
                    val progressionData =
                        if (exerciseProgressionByExerciseId.containsKey(it.key)) exerciseProgressionByExerciseId[it.key] else null

                    val exerciseProgression = progressionData?.first
                    val isDeloading = progressionData?.second ?: false

                    val exerciseHistories = it.value

                    val setDataList =
                        exerciseHistories.filter { setHistory -> setHistory.setData !is RestSetData }
                            .map { setHistory -> setHistory.setData }


                    val volume = setDataList.sumOf {
                        when (it) {
                            is BodyWeightSetData -> it.volume
                            is WeightSetData -> it.volume
                            else -> throw IllegalArgumentException("Unknown set type")
                        }
                    }.round(2)

                    val avgOneRepMax = setDataList.map { setData ->
                        when (setData) {
                            is BodyWeightSetData -> {
                                calculateOneRepMax(setData.getWeight(), setData.actualReps)
                            }

                            is WeightSetData -> {
                                calculateOneRepMax(setData.getWeight(), setData.actualReps)
                            }

                            else -> throw IllegalArgumentException("Unknown set type")
                        }
                    }.average()

                    val totalReps = setDataList.sumOf {
                        when (it) {
                            is BodyWeightSetData -> it.actualReps
                            is WeightSetData -> it.actualReps
                            else -> throw IllegalArgumentException("Unknown set type")
                        }
                    }

                    val averageLoad = volume / totalReps

                    var exerciseInfo = exerciseInfoDao.getExerciseInfoById(it.key!!)

                    if (exerciseInfo == null) {
                        val newExerciseInfo = ExerciseInfo(
                            id = it.key!!,
                            bestVolume = volume,
                            bestOneRepMax = avgOneRepMax,
                            bestAverageLoad = averageLoad,
                            successfulSessionCounter = 1u,
                            lastSessionVolume = volume,
                            lastSessionOneRepMax = avgOneRepMax,
                            lastSessionAverageLoad = averageLoad,
                            sessionFailedCounter = 0u,
                            lastSessionWasDeload = false
                        )
                        exerciseInfoDao.insert(newExerciseInfo)
                        exerciseInfos.add(newExerciseInfo)
                    } else {
                        if (exerciseInfo.bestVolume < volume) {
                            exerciseInfoDao.updateBestVolume(it.key!!, volume)
                        }

                        if (exerciseInfo.bestOneRepMax < avgOneRepMax) {
                            exerciseInfoDao.updateBestOneRepMax(it.key!!, avgOneRepMax)
                        }

                        if(exerciseInfo.bestAverageLoad < averageLoad){
                            exerciseInfoDao.updateBestAverageLoad(it.key!!, averageLoad)
                        }

                        if (exerciseInfo.lastSessionWasDeload && isDeloading == false) {
                            exerciseInfoDao.updateLastSessionWasDeload(it.key!!, false)
                        }

                        if (exerciseProgression != null) {
                            if(isDeloading){
                                exerciseInfoDao.updateLastSessionWasDeload(it.key!!, true)
                                exerciseInfoDao.updateSessionFailedCounter(it.key!!, 0u)
                                exerciseInfoDao.updateSuccessfulSessionCounter(it.key!!, 0u)
                            } else {
                                if (volume >= exerciseInfo.lastSessionVolume) {
                                    exerciseInfoDao.updateSuccessfulSessionCounter(
                                        it.key!!,
                                        exerciseInfo.successfulSessionCounter.inc()
                                    )
                                    exerciseInfoDao.updateSessionFailedCounter(it.key!!, 0u)
                                } else {
                                    exerciseInfoDao.updateSuccessfulSessionCounter(it.key!!, 0u)
                                    exerciseInfoDao.updateSessionFailedCounter(
                                        it.key!!,
                                        exerciseInfo.sessionFailedCounter.inc()
                                    )
                                }

                                exerciseInfoDao.updateLastSessionVolume(it.key!!, volume)
                                exerciseInfoDao.updateLastSessionOneRepMax(it.key!!, avgOneRepMax)
                                exerciseInfoDao.updateLastSessionAverageLoad(it.key!!, averageLoad)
                            }
                        }

                        exerciseInfo = exerciseInfoDao.getExerciseInfoById(it.key!!)
                        exerciseInfos.add(exerciseInfo!!)
                    }
                }

                val setHistoriesByExerciseId = executedSetsHistory
                    .filter { it.exerciseId != null }
                    .groupBy { it.exerciseId }

                val exercises = _selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + _selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
                var workoutComponents = _selectedWorkout.value.workoutComponents

                for (exercise in exercises) {
                    if(exercise.doNotStoreHistory) continue
                    val setHistories = setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order } ?: continue

                    workoutComponents = removeSetsFromExerciseRecursively(workoutComponents,exercise)

                    for (setHistory in setHistories) {
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

                workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
                updateWorkoutStore(newWorkoutStore)
            }

            onEnd()
        }
    }

    fun storeSetData() {
        val currentState = _workoutState.value
        if (!(currentState is WorkoutState.Set || currentState is WorkoutState.Rest)) return

        if (currentState is WorkoutState.Set) {
            val exercise = exercisesById[currentState.exerciseId]!!
            if (exercise.doNotStoreHistory || currentState.isWarmupSet) return
        }

        val newSetHistory = when (currentState) {
            is WorkoutState.Set -> SetHistory(
                id = UUID.randomUUID(),
                setId = currentState.set.id,
                setData = currentState.currentSetData,
                order = currentState.setIndex,
                skipped = currentState.skipped,
                exerciseId = currentState.exerciseId,
                startTime = currentState.startTime!!,
                endTime = LocalDateTime.now()
            )

            is WorkoutState.Rest -> SetHistory(
                id = UUID.randomUUID(),
                setId = currentState.set.id,
                setData = currentState.currentSetData,
                order = currentState.order,
                skipped = false,
                exerciseId = currentState.exerciseId,
                startTime = currentState.startTime!!,
                endTime = LocalDateTime.now()
            )

            else -> return
        }

        // Search for an existing entry in the history
        val existingIndex = when (currentState) {
            is WorkoutState.Set -> executedSetsHistory.indexOfFirst { it.setId == currentState.set.id && it.order == currentState.setIndex }
            is WorkoutState.Rest -> executedSetsHistory.indexOfFirst { it.setId == currentState.set.id && it.order == currentState.order }
            else -> return
        }
        if (existingIndex != -1) {
            executedSetsHistory[existingIndex] = newSetHistory.copy(
                id = executedSetsHistory[existingIndex].id,
                version = executedSetsHistory[existingIndex].version.inc()
            )
        } else {
            // If not found, add the new entry
            executedSetsHistory.add(newSetHistory)
        }
    }

    inline fun <reified T : SetData> getExecutedSetsDataByExerciseIdAndTakePriorToSetId(
        exerciseId: UUID,
        setId: UUID
    ): List<T> {
        return executedSetsHistory
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
                        currentSetData = initializeSetData(
                            RestSet(
                                workoutComponent.id,
                                workoutComponent.timeInSeconds
                            )
                        )
                    )

                    totalStates.add(restState)
                }

                is Superset -> {
                    val superset = workoutComponent as Superset
                    val queues = superset.exercises.map { ex -> mutableListOf(*addStatesFromExercise(ex).toTypedArray()) }
                    val out = mutableListOf<WorkoutState>()

                    // 1) Alternate WARM-UPS across exercises (keep their intrinsic rest)
                    var anyWarmups = true
                    while (anyWarmups) {
                        anyWarmups = false
                        for (q in queues) {
                            if (q.isEmpty() || q.first() !is WorkoutState.Set) continue
                            val s = q.first() as WorkoutState.Set
                            if (!s.isWarmupSet) continue
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
                        q.count { it is WorkoutState.Set && !(it as WorkoutState.Set).isWarmupSet }
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
                                        currentSetData = initializeSetData(restSet),
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
        val isDeloading = progressionData?.second

        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
        val exerciseAllSets = mutableListOf<Set>()

        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exercise.id)

        val exerciseSets = exercise.sets.filter { it !is RestSet }

        val oneRepMax = exerciseSets.map {
            when (it) {
                is BodyWeightSet -> {
                    val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    calculateOneRepMax(it.getWeight(relativeBodyWeight), it.reps)
                }

                is WeightSet -> calculateOneRepMax(it.weight, it.reps)
                else -> 0.0
            }
        }.average()

        if(exercise.generateWarmUpSets && equipment != null && (exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT)){
            val (workWeight,workReps) = exerciseSets.first().let  {
                when (it) {
                    is BodyWeightSet -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                        Pair(it.getWeight(relativeBodyWeight), it.reps)
                    }

                    is WeightSet -> {
                        Pair(it.weight, it.reps)
                    }

                    else -> throw IllegalArgumentException("Unknown set type")
                }
            }

            val intensity = workWeight / oneRepMax

            val numberOfWarmUpSets = when {
                intensity < 0.6 -> 2  // Lower intensity: 2 warm-up sets (lower range of 2-3)
                intensity in 0.6..0.8 -> 3  // Moderate intensity: 3 warm-up sets (lower range of 3-4)
                else -> 4  // High intensity: 4 warm-up sets (lower range of 4-5)
            }

            val availableWeights = when (exercise.exerciseType) {
                ExerciseType.WEIGHT -> getWeightByEquipment(equipment)

                ExerciseType.BODY_WEIGHT -> {
                    val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    (getWeightByEquipment(equipment).map { value -> relativeBodyWeight + value }.toSet() + setOf(relativeBodyWeight)).sorted()
                }

                else -> throw IllegalArgumentException("Unknown exercise type")
            }

            fun getSetWeight(desiredWeight: Double) : Double{
                return when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                        desiredWeight - relativeBodyWeight
                    }

                    ExerciseType.WEIGHT -> {
                        desiredWeight
                    }

                    else -> throw IllegalArgumentException("Unknown exercise type")
                }
            }

            fun getNewSet(id: UUID,weight: Double, reps: Int) : Set{
                return when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> {
                        BodyWeightSet(id, reps, weight, true)
                    }

                    ExerciseType.WEIGHT -> {
                        WeightSet(id, reps, weight, true)
                    }

                    else -> throw IllegalArgumentException("Unknown exercise type")
                }
            }

            fun buildWarmupSets(
                workWeight: Double,
                oneRepMax: Double,
                availableWeights: Collection<Double>,
                numberOfWarmUpSets: Int,
                maxPositiveDeviationFactor: Double = 1.15
            ): List<Pair<Double, Int>> {
                val protocols = listOf(
                    Triple(0.5, 5.0, 10),
                    Triple(0.6, 4.0, 8),
                    Triple(0.75, 3.0, 6),
                    Triple(0.9, 2.0, 3)
                )

                fun findBestWarmupWeight(
                    targetWeight: Double,
                    availableWeightsToConsider: List<Double>,
                    maxPositiveDeviationFactor: Double
                ): Double? {
                    if (availableWeightsToConsider.isEmpty()) {
                        return null
                    }

                    val suitableBelowOrAtTarget = availableWeightsToConsider.filter { it <= targetWeight }.maxOrNull()
                    if (suitableBelowOrAtTarget != null) {
                        return suitableBelowOrAtTarget
                    }

                    val lightestOverallAvailable = availableWeightsToConsider.first()
                    if (lightestOverallAvailable > targetWeight && lightestOverallAvailable <= targetWeight * maxPositiveDeviationFactor) {
                        return lightestOverallAvailable
                    }

                    return null
                }

                val sortedUniqueAvailableWeights = availableWeights.toSortedSet().toList()
                val chosenWeights = mutableSetOf<Double>()
                val warmUpSets = mutableListOf<Pair<Double, Int>>()

                for ((weightPercentage, targetRIR, maxReps) in protocols) {
                    if (warmUpSets.size >= numberOfWarmUpSets) break

                    val target = workWeight * weightPercentage
                    val potentialWeights = sortedUniqueAvailableWeights.filter { it !in chosenWeights }

                    val selectedWeight = findBestWarmupWeight(
                        targetWeight = target,
                        availableWeightsToConsider = potentialWeights,
                        maxPositiveDeviationFactor = maxPositiveDeviationFactor
                    )

                    if (selectedWeight != null) {
                        var reps = repsForTargetRIR(selectedWeight, oneRepMax, targetRIR)
                        reps = minOf(reps, maxReps.toDouble())

                        warmUpSets.add(selectedWeight to floor(reps).toInt().coerceAtLeast(2))
                        chosenWeights.add(selectedWeight)
                    }
                }

/*                if(warmUpSets.size < numberOfWarmUpSets && warmUpSets.isNotEmpty()){
                    fun lerp(start: Double, end: Double, fraction: Double): Double {
                        return start + fraction * (end - start)
                    }

                    val remainingSets = numberOfWarmUpSets - warmUpSets.size
                    val lastWarmUpSet = warmUpSets.last()
                    val lastWarmupWeight = lastWarmUpSet.first
                    val lastRIR = calculateRIR(lastWarmUpSet.first, lastWarmUpSet.second, oneRepMax)

                    for (i in 1..remainingSets) {
                        val fraction = i.toDouble() / (remainingSets + 1)
                        val weight = lerp(lastWarmupWeight, workWeight, fraction)

                        val rir = (lastRIR - i).coerceAtLeast(2).toDouble()
                        val reps = repsForTargetRIR(weight, oneRepMax, rir)

                        warmUpSets.add(weight to floor(reps).toInt().coerceAtLeast(2))
                    }
                }*/

                return warmUpSets
            }

            val actualWarmupSets = buildWarmupSets(
                workWeight,
                oneRepMax,
                availableWeights,
                numberOfWarmUpSets
            )

            actualWarmupSets.forEach {
                val (weight, reps) = it
                val setWeight = getSetWeight(weight)
                val newSet = getNewSet(UUID.randomUUID(), setWeight, reps)
                exerciseAllSets.add(newSet)
                var newRestSet = RestSet(UUID.randomUUID(), 60, false)
                exerciseAllSets.add(newRestSet)
            }

            exerciseAllSets.addAll(exercise.sets)
        }else{
            exerciseAllSets.addAll(exercise.sets)
        }

        val plateChangeResults = getPlateChangeResults(exercise, exerciseAllSets, equipment)

        val weightSets = exerciseAllSets.filterIsInstance<WeightSet>()

        for ((index, set) in exerciseAllSets.withIndex()) {
            if (set is RestSet) {
                val restSet = RestSet(set.id, set.timeInSeconds)

                val restState = WorkoutState.Rest(
                    set = restSet,
                    order = index.toUInt(),
                    currentSetData = initializeSetData(RestSet(set.id, set.timeInSeconds)),
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
                    is BodyWeightSet -> set.isWarmupSet
                    is WeightSet -> set.isWarmupSet
                    else -> false
                }

                val setState: WorkoutState.Set = WorkoutState.Set(
                    exercise.id,
                    set,
                    index.toUInt(),
                    previousSetData,
                    currentSetData,
                    historySet == null,
                    startTime = null,
                    false,
                    lowerBoundMaxHRPercent = exercise.lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent = exercise.upperBoundMaxHRPercent,
                    bodyWeight.value,
                    plateChangeResult,
                    exerciseInfo?.successfulSessionCounter?.toInt() ?: 0,
                    isDeloading ?: false,
                    isWarmupSet,
                    exercise.equipmentId?.let { getEquipmentById(it) },
                    oneRepMax
                )

                if(!isWarmupSet && exercise.intraSetRestInSeconds != null){
                    val restSet = RestSet(UUID.randomUUID(), exercise.intraSetRestInSeconds)

                    val restState = WorkoutState.Rest(
                        set = restSet,
                        order = index.toUInt(),
                        currentSetData = initializeSetData(restSet),
                        exerciseId = exercise.id
                    )
                    states.add(setState)
                    states.add(restState)
                    states.add(setState)
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
        workoutStateQueue.addLast(WorkoutState.Completed(startWorkoutTime!!))
    }

    open fun goToNextState() {
        if (workoutStateQueue.isEmpty()) return

        if (_workoutState.value !is WorkoutState.Preparing) {
            workoutStateHistory.add(_workoutState.value)
            _isHistoryEmpty.value = workoutStateHistory.isEmpty()
        }

        val newState = workoutStateQueue.pollFirst()!!

        if(newState is WorkoutState.Completed){
            newState.endWorkoutTime = LocalDateTime.now()
        }

        _workoutState.value = newState

        val nextWorkoutState =
            if (workoutStateQueue.isNotEmpty()) workoutStateQueue.peek()!! else null
        if (nextWorkoutState != null) {
            _nextWorkoutState.value = nextWorkoutState
        }
    }

    fun goToPreviousSet() {
        if (workoutStateHistory.isEmpty() || (workoutStateHistory.size == 1 && workoutStateHistory[0] === _workoutState.value)) return

        // Remove the current state from the queue and re-add it at the beginning to revisit later
        val currentState = _workoutState.value
        workoutStateQueue.addFirst(currentState)

        // Any state in the workoutStateQueue that was skipped (beyond the current state)
        // should now be placed back at the front of the queue to ensure they are the next targets.
        // This step may vary based on how you want to handle the reordering.
        // Assuming you want to reverse the order of "future" states so they are encountered in the original order:
        while (workoutStateHistory.isNotEmpty()) {
            val skippedState = workoutStateHistory.removeAt(workoutStateHistory.size - 1)

            if (skippedState is WorkoutState.Set) {
                _workoutState.value = skippedState
                break
            }

            workoutStateQueue.addFirst(skippedState)
        }

        // Update the next workout state based on the new queue
        _nextWorkoutState.value = workoutStateQueue.peek()!!
        _isHistoryEmpty.value = workoutStateHistory.isEmpty()

        //remove last element from executedSetsHistory
        if (executedSetsHistory.isNotEmpty()) {
            executedSetsHistory.removeAt(executedSetsHistory.size - 1)
        }
    }

    fun completeExercise() {
        val currentState = _workoutState.value as WorkoutState.Set
        val currentExerciseId = currentState.exerciseId

        while (workoutStateQueue.isNotEmpty()) {
            val state = workoutStateQueue.pollFirst()

            if (state is WorkoutState.Set) {
                val stateExerciseId = state.exerciseId
                if (stateExerciseId != currentExerciseId) {
                    _workoutState.value = state
                    break
                }
            }

            if (state is WorkoutState.Completed) {
                _workoutState.value = state
                break
            }
        }
    }

    // Extension function for rounding doubles
    protected fun Double.round(decimals: Int): Double {
        var multiplier = 1.0
        repeat(decimals) { multiplier *= 10 }
        return kotlin.math.round(this * multiplier) / multiplier
    }
}
