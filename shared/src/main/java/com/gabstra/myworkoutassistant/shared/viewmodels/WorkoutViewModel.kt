package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import android.util.Log
import android.widget.Toast
import androidx.annotation.FloatRange
import androidx.compose.runtime.State
import androidx.compose.runtime.asIntState
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
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.addSetToExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.removeSetsFromExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutComponentsRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.getNewSet
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
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
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
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


open class WorkoutViewModel : ViewModel() {
    var workoutStore by mutableStateOf(
        WorkoutStore(
            workouts = emptyList(),
            polarDeviceId = null,
            birthDateYear = 0,
            weightKg = 0.0,
            equipments = emptyList(),
            workloadProgressionLowerRange = 0.0,
            workloadProgressionUpperRange = 0.0
        )
    )

    fun getEquipmentById(id: UUID): Equipment? {
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
                workloadProgressionLowerRange = 0.0,
                workloadProgressionUpperRange = 0.0
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

    protected val weightsByEquipment: MutableMap<Equipment, kotlin.collections.Set<Double>> =
        mutableMapOf()

    fun getWeightByEquipment(equipment: Equipment?): kotlin.collections.Set<Double> {
        if (equipment == null) return emptySet()
        return weightsByEquipment[equipment] ?: emptySet()
    }

    val exerciseProgressionByExerciseId: MutableMap<UUID, Pair<VolumeDistributionHelper.ExerciseProgression?, Boolean>> =
        mutableMapOf()

    protected var currentWorkoutHistory by mutableStateOf<WorkoutHistory?>(null)

    var startWorkoutTime by mutableStateOf<LocalDateTime?>(null)

    open val exercisesById: Map<UUID, Exercise>
        get() = selectedWorkout.value.workoutComponents
            .filterIsInstance<Exercise>()
            .associateBy { it.id } + selectedWorkout.value.workoutComponents
            .filterIsInstance<Superset>().flatMap { it.exercises }
            .associateBy { it.id }

    val setsByExerciseId: Map<UUID, List<WorkoutState.Set>>
        get() = setStates
            .groupBy { it.exerciseId }

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

    fun upsertWorkoutRecord(setId: UUID) {
        viewModelScope.launch(Dispatchers.IO) {
            if (_workoutRecord == null) {
                _workoutRecord = WorkoutRecord(
                    id = UUID.randomUUID(),
                    workoutId = selectedWorkout.value.id,
                    setId = setId,
                    workoutHistoryId = currentWorkoutHistory!!.id
                )
            } else {
                _workoutRecord = _workoutRecord!!.copy(
                    setId = setId,
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
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
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
                generateWorkoutStates()
                workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
                triggerWorkoutNotification()
                onEnd()
            }
        }
    }

    public fun getAllExerciseWorkoutStates(exerciseId: UUID): List<WorkoutState.Set> {
        return allWorkoutStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }
    }

    private fun applyProgressions() {
        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        exercises.forEach { exercise ->
            if (exercise.doNotStoreHistory) return@forEach

            var currentExercise = exercise

            val progressionData =
                if (exerciseProgressionByExerciseId.containsKey(currentExercise.id)) exerciseProgressionByExerciseId[currentExercise.id] else null

            val exerciseProgression = progressionData?.first

            val equipment =
                exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
            val equipmentVolumeMultiplier = equipment?.volumeMultiplier ?: 1.0


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
                            val weight = if (equipment is Barbell) {
                                (setInfo.weight - equipment.barWeight - relativeBodyWeight) / equipmentVolumeMultiplier
                            } else if (equipment != null) {
                                (setInfo.weight - relativeBodyWeight) / equipmentVolumeMultiplier
                            } else {
                                setInfo.weight - relativeBodyWeight
                            }

                            BodyWeightSet(setId, setInfo.reps, weight)
                        }

                        ExerciseType.WEIGHT -> {
                            val weight = if (equipment is Barbell) {
                                (setInfo.weight - equipment.barWeight) / equipmentVolumeMultiplier
                            } else if (equipment != null) {
                                (setInfo.weight) / equipmentVolumeMultiplier
                            } else {
                                setInfo.weight
                            }

                            WeightSet(setId, setInfo.reps, weight)
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

        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>() + selectedWorkout.value.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
        val exerciseWithWeightSets = exercises.filter { it -> it.enabled }
            .filter { it.exerciseType == ExerciseType.WEIGHT || it.exerciseType == ExerciseType.BODY_WEIGHT  }

        exerciseWithWeightSets.map { exercise ->
            val equipment =
                exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }

            if (equipment != null && !weightsByEquipment.containsKey(equipment)) {
                val possibleCombinations = equipment.calculatePossibleCombinations()
                weightsByEquipment[equipment] = possibleCombinations
            }
        }

        // Process exercises sequentially
        exerciseWithWeightSets.forEach { exercise ->
            val result = processExercise(exercise)
            result?.let { (exerciseId, progression) ->
                exerciseProgressionByExerciseId[exerciseId] = progression
            }
        }
    }

    // Helper function to process a single exercise
    private suspend fun processExercise(exercise: Exercise): Pair<UUID, Pair<ExerciseProgression?, Boolean>>? {
        if (exercise.doNotStoreHistory) return null

        if (exercise.exerciseType == ExerciseType.BODY_WEIGHT && (exercise.bodyWeightPercentage == null)) {
            return null
        }

        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
        val equipmentVolumeMultiplier = equipment?.volumeMultiplier ?: 1.0

        val exerciseSets = exercise.sets.filter { it !is RestSet }

        var exerciseWorkload = 0.0
        var oneRepMax = 0.0
        var averageIntensityPerRep = 0.0
        var averageWorkloadPerRep = 0.0

        oneRepMax = exerciseSets.maxOf {
            when (it) {
                is BodyWeightSet -> {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    calculateOneRepMax(it.getWeight(equipment, relativeBodyWeight), it.reps)
                }

                is WeightSet -> calculateOneRepMax(it.getWeight(equipment), it.reps)
                else -> 0.0
            }
        }

        val setVolumes = exerciseSets.map {
            when (it) {
                is BodyWeightSet -> {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    val weight = it.getWeight(equipment, relativeBodyWeight)

                    val volume = weight * it.reps
                    volume
                }

                is WeightSet -> {
                    val weight = it.getWeight(equipment)
                    val volume = weight * it.reps
                    volume
                }

                else -> 0.0
            }
        }

        val exerciseVolume = setVolumes.sum()

        val setWorkloads = exerciseSets.map {
            when (it) {
                is BodyWeightSet -> {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    val weight = it.getWeight(equipment, relativeBodyWeight)
                    val intensity = weight / oneRepMax
                    val volume = weight * it.reps
                    volume * intensity
                }

                is WeightSet -> {
                    val weight = it.getWeight(equipment)
                    val intensity = weight / oneRepMax
                    val volume = weight * it.reps
                    volume * intensity
                }

                else -> 0.0
            }
        }

        exerciseWorkload = setWorkloads.sum()

        val totalReps = exerciseSets.sumOf {
            when (it) {
                is BodyWeightSet -> it.reps
                is WeightSet -> it.reps
                else -> 0
            }
        }

        averageIntensityPerRep = exerciseVolume / totalReps
        averageWorkloadPerRep = exerciseWorkload / totalReps

        if (exerciseWorkload == 0.0 || oneRepMax == 0.0) {
            Log.d("WorkoutViewModel", "Failed to process ${exercise.name}")
            return null
        }

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

        val maxLoadPercent = if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) 93.0 else exercise.maxLoadPercent
        val repsRange =
            if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) IntRange(3, 30) else IntRange(
                exercise.minReps,
                exercise.maxReps
            )

        Log.d(
            "WorkoutViewModel",
            "${exercise.name} (${exercise.exerciseType}) - Workload ${exerciseWorkload.round(2)} - 1RM ${
                String.format(
                    "%.2f",
                    oneRepMax
                ).replace(",", ".")
            }"
        )

        val oldSets = exerciseSets.map { set ->
            when (set) {
                is BodyWeightSet -> {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    set.getWeight(equipment,relativeBodyWeight)

                    if (equipment is Barbell) {
                        "${(set.getWeight(equipment,relativeBodyWeight) - relativeBodyWeight - equipment.barWeight) / equipmentVolumeMultiplier} kg x ${set.reps}"
                    } else {
                        "${ set.getWeight(equipment,relativeBodyWeight) - relativeBodyWeight} kg x ${set.reps}"
                    }
                }
                is WeightSet -> {
                    if (equipment is Barbell) {
                        "${(set.getWeight(equipment) - equipment.barWeight) / equipmentVolumeMultiplier} kg x ${set.reps}"
                    } else {
                        "${set.getWeight(equipment) / equipmentVolumeMultiplier} kg x ${set.reps}"
                    }
                }
                else -> throw IllegalArgumentException("Unknown set type")
            }
        }

        Log.d("WorkoutViewModel", "Old sets: ${oldSets.joinToString(", ")}")

        var exerciseProgression: ExerciseProgression? = null

        if (shouldDeload) {
            Log.d("WorkoutViewModel", "Deloading ${exercise.name}")
            //TODO: Implement deloading
        } else {
            exerciseProgression = VolumeDistributionHelper.generateExerciseProgression(
                exerciseWorkload,
                setWorkloads.min(),
                averageIntensityPerRep,
                averageWorkloadPerRep,
                exerciseWorkload / exerciseSets.size,
                oneRepMax,
                availableWeights,
                maxLoadPercent,
                repsRange,
                minSets = 3,
                maxSets = 5,
                workloadProgressionRange = FloatRange(workoutStore.workloadProgressionLowerRange, workoutStore.workloadProgressionUpperRange),
            )
        }

        if (exerciseProgression != null) {
            val newSets = exerciseProgression.sets.mapIndexed { index, set ->
                if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    if (equipment is Barbell) {
                        "${(set.weight - relativeBodyWeight - equipment.barWeight) / equipmentVolumeMultiplier} kg x ${set.reps}"
                    } else {
                        "${set.weight - relativeBodyWeight} kg x ${set.reps}"
                    }
                } else {
                    if (equipment is Barbell) {
                        "${(set.weight - equipment.barWeight) / equipmentVolumeMultiplier} kg x ${set.reps}"
                    } else {
                        "${set.weight / equipmentVolumeMultiplier} kg x ${set.reps}"
                    }

                }
            }

            Log.d("WorkoutViewModel", "New sets: ${newSets.joinToString(", ")}")

            Log.d(
                "WorkoutViewModel",
                "Progression found - Workload: ${exerciseProgression.originalWorkload.round(2)} -> ${exerciseProgression.workload.round(2)} (+${exerciseProgression.progressIncrease.round(2)}%)"
            )
        } else {
            Log.d("WorkoutViewModel", "Failed to find progression for ${exercise.name}")
        }

        Log.d("WorkoutViewModel", "# =========================================================================================== #")

        return exercise.id to Pair(exerciseProgression, shouldDeload)
    }

    fun resumeLastState() {
        if (_workoutRecord == null) return

        Log.d("WorkoutViewModel", "Resume last set")

        val targetSetId = _workoutRecord!!.setId
        if (_workoutState.value is WorkoutState.Set && (_workoutState.value as WorkoutState.Set).set.id == targetSetId) {
            Log.d("WorkoutViewModel", "Found set")
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _isResuming.value = true
            while (_workoutState.value !is WorkoutState.Finished) {
                goToNextState()

                if (_workoutState.value is WorkoutState.Set && (_workoutState.value as WorkoutState.Set).set.id == targetSetId) {
                    Log.d("WorkoutViewModel", "Found last Set")
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
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
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
                generateWorkoutStates()
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
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

    fun registerHeartBeat(heartBeat: Int) {
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
            workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))

            val targetSetId = when (_workoutState.value) {
                is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                else -> throw RuntimeException("Invalid state")
            }

            _workoutState.value = workoutStateQueue.pollFirst()!!

            while (_workoutState.value !is WorkoutState.Finished) {
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

            if (_workoutState.value !is WorkoutState.Finished) {
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

                    val currentExercise = exercisesById[it.key]!!

                    val equipment = currentExercise.equipmentId?.let { equipmentId ->
                        getEquipmentById(equipmentId)
                    }
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

                    val maxOneRepMax = setDataList.maxOf { setData ->
                        when (setData) {
                            is BodyWeightSetData -> {
                                calculateOneRepMax(setData.getWeight(equipment), setData.actualReps)
                            }

                            is WeightSetData -> {
                                calculateOneRepMax(setData.getWeight(equipment), setData.actualReps)
                            }

                            else -> throw IllegalArgumentException("Unknown set type")
                        }
                    }


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
                            bestOneRepMax = maxOneRepMax,
                            bestAverageLoad = averageLoad,
                            successfulSessionCounter = 1u,
                            lastSessionVolume = volume,
                            lastSessionOneRepMax = maxOneRepMax,
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

                        if (exerciseInfo.bestOneRepMax < maxOneRepMax) {
                            exerciseInfoDao.updateBestOneRepMax(it.key!!, maxOneRepMax)
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
                                exerciseInfoDao.updateLastSessionOneRepMax(it.key!!, maxOneRepMax)
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
            if (exercise.doNotStoreHistory) return
        }

        val newSetHistory = when (currentState) {
            is WorkoutState.Set -> SetHistory(
                id = UUID.randomUUID(),
                setId = currentState.set.id,
                setData = currentState.currentSetData,
                order = currentState.order,
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
            is WorkoutState.Set -> executedSetsHistory.indexOfFirst { it.setId == currentState.set.id && it.order == currentState.order }
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

    protected suspend fun generateWorkoutStates() {
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

                    val exerciseStates = superset.exercises.map { exercise ->
                        mutableListOf(*addStatesFromExercise(exercise).toTypedArray())
                    }

                    val count = exerciseStates.minOfOrNull { it.size }!!
                    val states = mutableListOf<WorkoutState>()

                    for (i in 0 until count) {
                        //get the first element of each list

                        val items = mutableListOf<WorkoutState>()

                        for (exerciseState in exerciseStates) {
                            if (exerciseState.isNotEmpty()) {
                                items.add(exerciseState.first())
                                exerciseState.removeAt(0)
                            }
                        }

                        //check if all the items are of type WorkoutState.Set
                        val allItemsAreSets = items.all { it is WorkoutState.Set }

                        if(allItemsAreSets){
                            states.addAll(items)
                        }else{
                            continue
                        }

                        if(i != count - 1){
                            val restSet = RestSet(UUID.randomUUID(),superset.timeInSeconds)
                            val restState = WorkoutState.Rest(
                                set = restSet,
                                order = (i+1).toUInt(),
                                currentSetData = initializeSetData(RestSet(UUID.randomUUID(), superset.timeInSeconds))
                            )
                            states.add(restState)
                        }
                    }

                    while(exerciseStates.any { it.isNotEmpty() }){
                        val items = mutableListOf<WorkoutState>()

                        for (exerciseState in exerciseStates) {
                            if (exerciseState.isNotEmpty()) {
                                items.add(exerciseState.first())
                                exerciseState.removeAt(0)
                            }
                        }

                        states.addAll(items)
                    }

                    totalStates.addAll(states)
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

        totalStates.forEach {
            workoutStateQueue.addLast(it)
            allWorkoutStates.add(it)
            if(it is WorkoutState.Set){
                setStates.addLast(it)
            }
        }
    }

    protected fun getPlateChangeResults(
        exercise: Exercise,
        exerciseSets: List<Set>,
        equipment: Equipment?,
        initialSetup: List<Double> = emptyList()
    ): List<PlateCalculator.Companion.PlateChangeResult> {
        val plateChangeResults = mutableListOf<PlateCalculator.Companion.PlateChangeResult>()

        if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
            val sets = exerciseSets.filterIsInstance<WeightSet>()
            val setWeights = sets.map { it.getWeight(equipment) }.toList()
            val plateWeights = equipment.availablePlates.map { it.weight }
                .toList() + equipment.additionalPlates.map { it.weight }.toList()

            try {
                plateChangeResults.addAll(
                    PlateCalculator.calculatePlateChanges(
                        plateWeights,
                        setWeights,
                        equipment.barWeight,
                        initialSetup,
                        multiplier = equipment.volumeMultiplier
                    )
                )
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
        val exerciseSets = exercise.sets.filter { it !is RestSet }

        val exerciseVolume = exerciseProgression?.originalWorkload
            ?: exerciseSets.sumOf {
                when (it) {
                    is BodyWeightSet -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                        it.getWeight(equipment, relativeBodyWeight) * it.reps
                    }

                    is WeightSet -> {
                        it.getWeight(equipment) * it.reps
                    }

                    else -> 0.0
                }
            }

        val plateChangeResults = getPlateChangeResults(exercise, exerciseSets, equipment)

        val exerciseInfo = exerciseInfoDao.getExerciseInfoById(exercise.id)

        for ((index, set) in exercise.sets.withIndex()) {
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
                        currentSetData.copy(volume = currentSetData.calculateVolume(equipment))
                } else if (currentSetData is WeightSetData) {
                    currentSetData =
                        currentSetData.copy(volume = currentSetData.calculateVolume(equipment))
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

                val plateChangeResult = plateChangeResults.getOrNull(exerciseSets.indexOf(set))

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
                    exerciseVolume,
                    exerciseProgression?.progressIncrease
                )

                states.add(setState)
            }
        }

        return states
    }

    fun setWorkoutStart() {
        val startTime = LocalDateTime.now()
        startWorkoutTime = startTime
        workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))
    }

    fun goToNextState() {
        if (workoutStateQueue.isEmpty()) return

        if (_workoutState.value !is WorkoutState.Preparing) {
            workoutStateHistory.add(_workoutState.value)
            _isHistoryEmpty.value = workoutStateHistory.isEmpty()
        }

        val newState = workoutStateQueue.pollFirst()!!
        val nextWorkoutState =
            if (workoutStateQueue.isNotEmpty()) workoutStateQueue.peek()!! else null
        _workoutState.value = newState
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

            if (state is WorkoutState.Finished) {
                _workoutState.value = state
                break
            }
        }
    }

    // Helper function for calculating one rep max
    protected fun calculateOneRepMax(weight: Double, reps: Int): Double {
        return weight / (1.0278 - (0.0278 * reps))
    }

    // Extension function for rounding doubles
    protected fun Double.round(decimals: Int): Double {
        var multiplier = 1.0
        repeat(decimals) { multiplier *= 10 }
        return kotlin.math.round(this * multiplier) / multiplier
    }
}
