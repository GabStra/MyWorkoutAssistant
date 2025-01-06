package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import android.widget.Toast
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
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutComponentsRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.getNewSet
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
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper.DistributedWorkout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
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


sealed class WorkoutState {
    data class Preparing(
        val dataLoaded: Boolean
    ) : WorkoutState()

    data class Set(
        val exerciseId: UUID,
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        val previousSetData: SetData?,
        var currentSetData: SetData,
        val hasNoHistory: Boolean,
        var skipped: Boolean,
        val targetZone: Int? = null,
        val currentBodyWeight: Double,
        val plateChange: PlateCalculator.Companion.PlateChange? = null,
        val progressionValue: Double? = null,
    ) : WorkoutState()

    data class Rest(
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        var currentSetData: SetData,
        val exerciseId: UUID? = null,
    ) : WorkoutState()

    data class Finished(val startWorkoutTime: LocalDateTime) : WorkoutState()
}

class AppViewModel : ViewModel() {
    private var workoutStore by mutableStateOf(
        WorkoutStore(
            workouts = emptyList(),
            polarDeviceId = null,
            birthDateYear = 0,
            weightKg = 0.0,
            equipments = emptyList()
        )
    )

    fun getEquipmentById(id: UUID): Equipment? {
        return workoutStore.equipments.find { it.id == id }
    }

    private val _isPaused = mutableStateOf(false) // Private mutable state
    val isPaused: State<Boolean> = _isPaused // Public read-only State access

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

    private val allWorkoutStates: MutableList<WorkoutState> = mutableListOf()

    var polarDeviceId: String = ""
        get() = workoutStore.polarDeviceId ?: ""

    private var dataClient: DataClient? = null
    var phoneNode by mutableStateOf<Node?>(null)

    val isPhoneConnectedAndHasApp: Boolean
        get() = phoneNode != null


    fun resetWorkoutStore() {
        updateWorkoutStore(
            WorkoutStore(
                workouts = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0.0,
                equipments = emptyList()
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

    fun initDataClient(client: DataClient) {
        dataClient = client
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

    private lateinit var workoutRecordDao: WorkoutRecordDao

    private lateinit var workoutHistoryDao: WorkoutHistoryDao

    private lateinit var setHistoryDao: SetHistoryDao

    private lateinit var exerciseInfoDao: ExerciseInfoDao

    private lateinit var workoutStoreRepository: WorkoutStoreRepository

    private val _workoutState =
        MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()

    private val _nextWorkoutState =
        MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val nextWorkoutState = _nextWorkoutState.asStateFlow()

    public val executedSetsHistory: MutableList<SetHistory> = mutableListOf()

    private val heartBeatHistory: ConcurrentLinkedQueue<Int> = ConcurrentLinkedQueue()

    private val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    private val workoutStateHistory: MutableList<WorkoutState> = mutableListOf()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    private val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    public val latestSetHistoriesByExerciseId: MutableMap<UUID, List<SetHistory>> = mutableMapOf()

    public val latestSetHistoryMap: MutableMap<UUID, SetHistory> = mutableMapOf()

    val distributedWorkoutByExerciseIdMap: MutableMap<UUID, Pair<VolumeDistributionHelper.DistributedWorkout?, Boolean>?> =
        mutableMapOf()

    private var currentWorkoutHistory by mutableStateOf<WorkoutHistory?>(null)

    private var startWorkoutTime by mutableStateOf<LocalDateTime?>(null)

    val exercisesById: Map<UUID, Exercise>
        get() = selectedWorkout.value.workoutComponents
            .filterIsInstance<Exercise>()
            .associateBy { it.id }

    val setsByExerciseId: Map<UUID, List<WorkoutState.Set>>
        get() = setStates
            .groupBy { it.exerciseId }

    private var _workoutRecord by mutableStateOf<WorkoutRecord?>(null)

    private val _isResuming = MutableStateFlow<Boolean>(false)
    val isResuming = _isResuming.asStateFlow()

    private val _isRefreshing = MutableStateFlow<Boolean>(false)
    val isRefreshing = _isRefreshing.asStateFlow()

    private val _hasWorkoutRecord = MutableStateFlow<Boolean>(false)
    val hasWorkoutRecord = _hasWorkoutRecord.asStateFlow()

    private val _hasExercises = MutableStateFlow<Boolean>(false)
    val hasExercises = _hasExercises.asStateFlow()

    private val _isSkipDialogOpen = MutableStateFlow<Boolean>(false)

    val isSkipDialogOpen = _isSkipDialogOpen.asStateFlow()

    private val _enableWorkoutNotificationFlow = MutableStateFlow<String?>(null)
    val enableWorkoutNotificationFlow = _enableWorkoutNotificationFlow.asStateFlow()

    fun triggerWorkoutNotification() {
        _enableWorkoutNotificationFlow.value = System.currentTimeMillis().toString()
    }

    // Setter method to open dialog
    fun openSkipDialog() {
        _isSkipDialogOpen.value = true
    }

    // Setter method to close dialog
    fun closeSkipDialog() {
        _isSkipDialogOpen.value = false
    }

    private val _lightScreenUp = Channel<Unit>(Channel.BUFFERED)
    val lightScreenUp = _lightScreenUp.receiveAsFlow()

    fun lightScreenUp() {
        viewModelScope.launch {
            _lightScreenUp.send(Unit)
        }
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
            }
        }
    }

    fun sendAll(context: Context) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                val statuses = mutableListOf<Boolean>()
                val workouts = workoutStore.workouts.filter { it.enabled && it.isActive }

                if (workouts.isEmpty()) return@withContext

                workouts.forEach {
                    val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(it.id)
                        ?: return@forEach
                    val setHistories =
                        setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                    val exercises = it.workoutComponents.filterIsInstance<Exercise>()
                    val exerciseInfos = exercises.mapNotNull { exercise ->
                        exerciseInfoDao.getExerciseInfoById(exercise.id)
                    }

                    val result = sendWorkoutHistoryStore(
                        dataClient!!,
                        WorkoutHistoryStore(
                            WorkoutHistory = workoutHistory,
                            SetHistories = setHistories,
                            ExerciseInfos = exerciseInfos
                        )
                    )
                    statuses.add(result)
                }

                if (statuses.contains(false)) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT)
                            .show()
                    }
                } else {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(context, "Data sent to phone", Toast.LENGTH_SHORT).show()
                    }
                }

            }
        }
    }

    private fun getWorkoutRecord(workout: Workout) {
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

    fun resumeWorkoutFromRecord(onEnd: () -> Unit = {}) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
                workoutStateQueue.clear()
                workoutStateHistory.clear()
                _isHistoryEmpty.value = workoutStateHistory.isEmpty()
                setStates.clear()
                allWorkoutStates.clear()
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
                Log.d("WorkoutViewModel", "Resumed workout")
                triggerWorkoutNotification()
                onEnd()
                lightScreenUp()
            }
        }
    }

    public fun getAllExerciseWorkoutStates(exerciseId: UUID): List<WorkoutState.Set> {
        return allWorkoutStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }
    }

    private fun applyProgressions() {
        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>()

        exercises.forEach { exercise ->
            if (exercise.doNotStoreHistory) return@forEach

            var currentExercise = exercise

            val distributedWorkout =
                if (distributedWorkoutByExerciseIdMap.containsKey(currentExercise.id)) distributedWorkoutByExerciseIdMap[currentExercise.id] else null

            val equipment =
                exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
            val equipmentVolumeMultiplier = equipment?.volumeMultiplier ?: 1.0


            if (distributedWorkout != null) {
                if (distributedWorkout.first != null) {
                    val distributedSets = distributedWorkout.first!!.sets
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
                    currentExercise = newExercise
                    updateWorkout(exercise, newExercise)
                }

                if (distributedWorkout.second) {
                    val newSets = currentExercise.sets.toMutableList()
                    val newRestSet = RestSet(UUID.randomUUID(), 20, true)
                    newSets.add(newRestSet)

                    val newSet = when (val new = getNewSet(currentExercise.sets.last())) {
                        is BodyWeightSet -> new.copy(reps = 3)
                        is WeightSet -> new.copy(reps = 3)
                        else -> throw IllegalArgumentException("Unknown set type")
                    }

                    newSets.add(newSet)
                    val newExercise = exercise.copy(sets = newSets)
                    updateWorkout(exercise, newExercise)
                }
            }
        }
    }

    private suspend fun generateProgressions() {
        distributedWorkoutByExerciseIdMap.clear()

        val exerciseWithWeightSets = selectedWorkout.value.workoutComponents
            .filter { it.enabled && it is Exercise && (it.exerciseType == ExerciseType.WEIGHT || it.exerciseType == ExerciseType.BODY_WEIGHT) }
            .filterIsInstance<Exercise>()

        // Process exercises in parallel
        val results = coroutineScope {
            exerciseWithWeightSets.map { exercise ->
                async(Dispatchers.IO) {
                    processExercise(exercise)
                }
            }.awaitAll()
        }

        results.filterNotNull().forEach { (exerciseId, distribution) ->
            distributedWorkoutByExerciseIdMap[exerciseId] = distribution
        }


       /* // Process exercises sequentially
        exerciseWithWeightSets.forEach { exercise ->
            val result = processExercise(exercise)
            result?.let { (exerciseId, distribution) ->
                val oldSets = exercise.sets.filter { it is BodyWeightSet || it is WeightSet}.joinToString { it -> when(it){
                    is BodyWeightSet -> "(${it.reps} reps x ${it.additionalWeight} kg)"
                    is WeightSet -> "(${it.reps} reps x ${it.weight} kg)"
                    else -> ""
                } }
                Log.d("WorkoutViewModel", "Old sets: $oldSets")
                distributedWorkoutByExerciseIdMap[exerciseId] = distribution
            }
        }*/
    }

    // Helper function to process a single exercise
    private suspend fun processExercise(exercise: Exercise): Pair<UUID, Pair<DistributedWorkout?, Boolean>>? {
        if (exercise.doNotStoreHistory) return null

        if (exercise.exerciseType == ExerciseType.BODY_WEIGHT && (exercise.bodyWeightPercentage == null)) {
            return null
        }

        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
        val equipmentVolumeMultiplier = equipment?.volumeMultiplier ?: 1.0

        var totalVolume = 0.0
        var avg1RM = 0.0

        val totalHistoricalSetDataList = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> getHistoricalSetsDataByExerciseId<WeightSetData>(exercise.id)
            ExerciseType.BODY_WEIGHT -> getHistoricalSetsDataByExerciseId<BodyWeightSetData>(
                exercise.id
            )

            else -> emptyList()
        }

        if (totalHistoricalSetDataList.isNotEmpty()) {
            /*
            val historicalSets = totalHistoricalSetDataList.filter { it is BodyWeightSetData || it is WeightSetData}.joinToString { it -> when(it){
                is BodyWeightSetData -> "(${it.additionalWeight} kg x ${it.actualReps} reps - volume ${it.volume})"
                is WeightSetData -> "(${it.actualWeight} kg x ${it.actualReps} reps - volume ${it.volume})"
                else -> ""
            } }
            Log.d("WorkoutViewModel", "${exercise.name} Historical Sets: $historicalSets")
            */

            totalVolume = totalHistoricalSetDataList.sumOf {
                when (it) {
                    is BodyWeightSetData -> it.volume
                    is WeightSetData -> it.volume
                    else -> 0.0
                }
            }

            avg1RM = (totalHistoricalSetDataList.sumOf {
                when (it) {
                    is BodyWeightSetData -> calculateOneRepMax(
                        it.getWeight(equipment),
                        it.actualReps
                    )

                    is WeightSetData -> calculateOneRepMax(it.getWeight(equipment), it.actualReps)
                    else -> 0.0
                }
            }) / totalHistoricalSetDataList.size
        } else {
            val exerciseSets = exercise.sets.filter { it !is RestSet }

            totalVolume = exerciseSets.sumOf {
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

            avg1RM = (exerciseSets.sumOf {
                when (it) {
                    is BodyWeightSet -> {
                        val relativeBodyWeight =
                            bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                        calculateOneRepMax(it.getWeight(equipment, relativeBodyWeight), it.reps)
                    }
                    is WeightSet -> calculateOneRepMax(it.getWeight(equipment), it.reps)
                    else -> 0.0
                }
            }) / exerciseSets.size
        }

        if (totalVolume == 0.0 || avg1RM == 0.0) {
            Log.d("WorkoutViewModel", "No historical data for ${exercise.name}")
            return null
        }

        val availableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> exercise.equipmentId?.let { getEquipmentById(it)!!.calculatePossibleCombinations() }
                ?: emptySet()

            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    getEquipmentById(it)!!.calculatePossibleCombinations()
                        .map { value -> relativeBodyWeight + value }.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }

            else -> throw IllegalArgumentException("Unknown exercise type")
        }

        val loadPercentageRange = Pair(40.0, 93.0)
        val repsRange = IntRange(3, 30)

        val volumeIncreasePercent =
            if (exercise.volumeIncreasePercent > 3) 3.0f else exercise.volumeIncreasePercent

        val distributedWorkout = VolumeDistributionHelper.distributeVolumeWithMinimumIncrease(
            totalVolume,
            avg1RM,
            availableWeights,
            volumeIncreasePercent,
            loadPercentageRange,
            repsRange,
            exercise.fatigueFactor
        )

        Log.d(
            "WorkoutViewModel",
            "${exercise.name} (${exercise.exerciseType}) - volume $totalVolume - avg 1RM ${
                String.format(
                    "%.2f",
                    avg1RM
                ).replace(",", ".")
            } desired increase in percentage: ${volumeIncreasePercent}% "
        )

        if (distributedWorkout != null) {
            distributedWorkout.sets.forEachIndexed { index, set ->
                if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
                    val relativeBodyWeight =
                        bodyWeight.value * (exercise.bodyWeightPercentage!! / 100)
                    if (equipment is Barbell) {
                        Log.d(
                            "WorkoutViewModel",
                            "Set ${index + 1}: ${set.reps} reps, ${(set.weight - relativeBodyWeight - equipment.barWeight) / equipmentVolumeMultiplier} kg"
                        )
                    } else {
                        Log.d(
                            "WorkoutViewModel",
                            "Set ${index + 1}: ${set.reps} reps, ${set.weight - relativeBodyWeight} kg"
                        )
                    }
                } else {
                    if (equipment is Barbell) {
                        Log.d(
                            "WorkoutViewModel",
                            "Set ${index + 1}: ${set.reps} reps, ${(set.weight - equipment.barWeight) / equipmentVolumeMultiplier} kg"
                        )
                    } else {
                        Log.d(
                            "WorkoutViewModel",
                            "Set ${index + 1}: ${set.reps} reps, ${set.weight / equipmentVolumeMultiplier} kg"
                        )
                    }

                }
            }
            Log.d(
                "WorkoutViewModel",
                "Progression found - volume $totalVolume -> ${distributedWorkout.totalVolume} +${
                    String.format(
                        "%.2f",
                        ((distributedWorkout.totalVolume - totalVolume) / totalVolume) * 100
                    )
                }% Average percentage load: ${
                    String.format(
                        "%.2f",
                        distributedWorkout.averagePercentLoad
                    ).replace(",", ".")
                }%"
            )
        } else {
            Log.d("WorkoutViewModel", "Failed to distribute volume for ${exercise.name}")
        }

        return exercise.id to Pair(distributedWorkout, false)
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

    fun startWorkout() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
                workoutStateQueue.clear()
                workoutStateHistory.clear()
                _isHistoryEmpty.value = workoutStateHistory.isEmpty()
                setStates.clear()
                allWorkoutStates.clear()
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
                lightScreenUp()
            }
        }
    }

    fun sendWorkoutHistoryToPhone(onEnd: (Boolean) -> Unit = {}) {
        viewModelScope.launch(Dispatchers.IO) {
            val workoutHistory =
                workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)
            if (workoutHistory == null) {
                withContext(Dispatchers.Main) {
                    onEnd(false)
                }
                return@launch
            }

            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

            val exerciseInfos =
                selectedWorkout.value.workoutComponents.filter { it is Exercise }.mapNotNull {
                    val exercise = it as Exercise
                    exerciseInfoDao.getExerciseInfoById(exercise.id)
                }

            dataClient?.let {
                sendWorkoutHistoryStore(
                    it, WorkoutHistoryStore(
                        WorkoutHistory = workoutHistory,
                        SetHistories = setHistories,
                        ExerciseInfos = exerciseInfos
                    )
                )
            }

            withContext(Dispatchers.Main) {
                onEnd(true)
            }
        }
    }

    private suspend fun restoreExecutedSets() {
        if (_workoutRecord == null) return;
        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>()

        executedSetsHistory.clear()
        exercises.filter { !it.doNotStoreHistory }.forEach { exercise ->
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                _workoutRecord!!.workoutHistoryId,
                exercise.id
            )

            executedSetsHistory.addAll(setHistories);
        }
    }

    private suspend fun loadWorkoutHistory() {
        val workoutHistories = workoutHistoryDao
            .getAllWorkoutHistories()
            .filter { it.globalId == selectedWorkout.value.globalId && it.isDone }
            .sortedByDescending { it.date }

        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>()

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
        if (heartBeat > 0) heartBeatHistory.add(heartBeat)
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

    private fun RefreshAndGoToNextState() {
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

    fun pushAndStoreWorkoutData(
        isDone: Boolean,
        context: Context? = null,
        forceNotSend: Boolean = false,
        onEnd: () -> Unit = {}
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
                    val equipment = exercisesById[it.key]?.equipmentId?.let { equipmentId ->
                        getEquipmentById(equipmentId)
                    }
                    val setDataList =
                        it.value.filter { setHistory -> setHistory.setData !is RestSetData }
                            .map { setHistory -> setHistory.setData }

                    val volume = setDataList.sumOf {
                        when (it) {
                            is BodyWeightSetData -> it.volume
                            is WeightSetData -> it.volume
                            else -> throw IllegalArgumentException("Unknown set type")
                        }
                    }

                    val avgOneRepMax = (setDataList.sumOf { setData ->
                        when (setData) {
                            is BodyWeightSetData -> {
                                calculateOneRepMax(setData.getWeight(equipment), setData.actualReps)
                            }

                            is WeightSetData -> {
                                calculateOneRepMax(setData.getWeight(equipment), setData.actualReps)
                            }

                            else -> throw IllegalArgumentException("Unknown set type")
                        }
                    }) / setDataList.size

                    val exerciseInfo = exerciseInfoDao.getExerciseInfoById(it.key!!)

                    if (exerciseInfo == null) {
                        val newExerciseInfo = ExerciseInfo(
                            id = it.key!!,
                            bestVolume = volume,
                            avgOneRepMax = avgOneRepMax
                        )
                        exerciseInfoDao.insert(newExerciseInfo)
                        exerciseInfos.add(newExerciseInfo)
                    } else {
                        if (exerciseInfo.bestVolume < volume) {
                            exerciseInfoDao.updateBestVolume(it.key!!, volume)
                        }

                        if (exerciseInfo.avgOneRepMax < avgOneRepMax) {
                            exerciseInfoDao.updateAvgOneRepMax(it.key!!, avgOneRepMax)
                        }

                        exerciseInfos.add(exerciseInfo)
                    }
                }

                val currentWorkoutStore = workoutStoreRepository.getWorkoutStore()
                val newWorkoutStore =
                    currentWorkoutStore.copy(workouts = currentWorkoutStore.workouts.map {
                        if (it.id == _selectedWorkout.value.id) {
                            it.copy(workoutComponents = _selectedWorkout.value.workoutComponents)
                        } else {
                            it
                        }
                    })

                workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
                updateWorkoutStore(newWorkoutStore)
            }

            val currentState = _workoutState.value
            val shouldSendData = currentState != setStates.last() || isDone

            if (forceNotSend || !shouldSendData) {
                onEnd()
                return@launch
            }

            withContext(Dispatchers.IO) {
                val result = sendWorkoutHistoryStore(
                    dataClient!!,
                    WorkoutHistoryStore(
                        WorkoutHistory = currentWorkoutHistory!!,
                        SetHistories = executedSetsHistory,
                        ExerciseInfos = exerciseInfos
                    )
                )

                if (context != null && !result) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT)
                            .show()
                    }
                }

                withContext(Dispatchers.Main) {
                    onEnd()
                }
            }
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
                exerciseId = currentState.exerciseId
            )

            is WorkoutState.Rest -> SetHistory(
                id = UUID.randomUUID(),
                setId = currentState.set.id,
                setData = currentState.currentSetData,
                order = currentState.order,
                skipped = false,
                exerciseId = currentState.exerciseId
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

        //return exercisesById[exerciseId]!!.sets.filter { latestSetHistoryMap.contains(it.id) && latestSetHistoryMap[it.id]!!.setData is T }.map{ latestSetHistoryMap[it.id]!!.setData as T }
    }

    private fun generateWorkoutStates() {
        val workoutComponents = selectedWorkout.value.workoutComponents.filter { it.enabled }
        for ((index, workoutComponent) in workoutComponents.withIndex()) {
            when (workoutComponent) {
                is Exercise -> addStatesFromExercise(workoutComponent)
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
                    workoutStateQueue.addLast(restState)
                    allWorkoutStates.add(restState)
                }
            }
        }
    }

    private fun addStatesFromExercise(exercise: Exercise) {
        if (exercise.sets.isEmpty()) return

        val exerciseSets = exercise.sets.filter { it !is RestSet }
        val equipment = exercise.equipmentId?.let { equipmentId -> getEquipmentById(equipmentId) }
        val plateChanges = mutableListOf<PlateCalculator.Companion.PlateChange>()
        val distributedWorkout =
            if (distributedWorkoutByExerciseIdMap.containsKey(exercise.id)) distributedWorkoutByExerciseIdMap[exercise.id] else null

        if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
            val sets = exerciseSets.filterIsInstance<WeightSet>()
            val setWeights = sets.map { it.getWeight(equipment) }.toList()

            val plateWeights = equipment.availablePlates.map { it.weight }
                .toList() + equipment.additionalPlates.map { it.weight }.toList()
            try {
                plateChanges.addAll(
                    PlateCalculator.calculatePlateChanges(
                        plateWeights,
                        setWeights,
                        equipment.barWeight,
                        multiplier = equipment.volumeMultiplier
                    )
                )
            } catch (_: Exception) {
            }
        }

        for ((index, set) in exercise.sets.withIndex()) {
            if (set is RestSet) {
                val restSet = RestSet(set.id, set.timeInSeconds)

                val restState = WorkoutState.Rest(
                    set = restSet,
                    order = index.toUInt(),
                    currentSetData = initializeSetData(RestSet(set.id, set.timeInSeconds)),
                    exerciseId = exercise.id
                )
                workoutStateQueue.addLast(restState)
                allWorkoutStates.add(restState)
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
                    if (isSetDataValid(set, historySetData) && distributedWorkout == null) {
                        currentSetData = copySetData(historySetData)
                        previousSetData = historySet.setData
                    }
                }

                val plateChange = plateChanges.getOrNull(exerciseSets.indexOf(set))

                val setState: WorkoutState.Set = WorkoutState.Set(
                    exercise.id,
                    set,
                    index.toUInt(),
                    previousSetData,
                    currentSetData,
                    historySet == null,
                    false,
                    exercise.targetZone,
                    bodyWeight.value,
                    plateChange,
                    distributedWorkout?.first?.progressIncrease
                )
                workoutStateQueue.addLast(setState)
                setStates.addLast(setState)
                allWorkoutStates.add(setState)
            }
        }
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
        val nextWorkoutState =  if (workoutStateQueue.isNotEmpty()) workoutStateQueue.peek()!! else null
        _workoutState.value = newState
        if(nextWorkoutState != null) {
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
    }

    fun skipExercise() {
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
}