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
import com.gabstra.myworkoutassistant.shared.getNewSet
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.ProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper
import com.gabstra.myworkoutassistant.shared.utils.VolumeDistributionHelper.DistributedWorkout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
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


sealed class WorkoutState {
    data class Preparing (
        val dataLoaded :Boolean
    ): WorkoutState()
    data class Set(
        val exerciseId: UUID,
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        val previousSetData: SetData?,
        var currentSetData:  SetData,
        val hasNoHistory: Boolean,
        var skipped: Boolean
    ) : WorkoutState()
    data class Rest(
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: UInt,
        var currentSetData:  SetData,
        val exerciseId: UUID? = null,
    ) : WorkoutState()
    data class Finished(val startWorkoutTime:LocalDateTime) : WorkoutState()
}

class AppViewModel : ViewModel(){
    private var workoutStore by mutableStateOf(
            WorkoutStore(
                workouts = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0,
                weightKg = 0f
        )
    )

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

    private var _backupProgress = mutableStateOf(0f)
    val backupProgress: State<Float> = _backupProgress

    // Create a function to update the backup progress
    fun setBackupProgress(progress: Float) {
        _backupProgress.value = progress
    }

    var polarDeviceId: String = ""
        get() = workoutStore.polarDeviceId?: ""

    private var dataClient: DataClient? = null
    var phoneNode by mutableStateOf<Node?>(null)

    val isPhoneConnectedAndHasApp: Boolean
        get() = phoneNode != null


    fun updateWorkoutStore(newWorkoutStore: WorkoutStore) {
        workoutStore = newWorkoutStore
        _workouts.value = workoutStore.workouts.filter { it.enabled && it.isActive }
        val currentYear = Calendar.getInstance().get(Calendar.YEAR)
        _userAge.intValue =  currentYear - workoutStore.birthDateYear
    }

    fun initDataClient(client: DataClient) {
        dataClient = client
    }

    fun initExerciseHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        setHistoryDao = db.setHistoryDao()
    }

    fun initWorkoutHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        workoutHistoryDao= db.workoutHistoryDao()
    }

    fun initWorkoutRecordDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        workoutRecordDao = db.workoutRecordDao()
    }

    fun initExerciseInfoDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        exerciseInfoDao = db.exerciseInfoDao()
    }

    fun initWorkoutStoreRepository(workoutStoreRepository: WorkoutStoreRepository){
        this.workoutStoreRepository = workoutStoreRepository
    }

    private val _selectedWorkout = mutableStateOf(Workout(UUID.randomUUID(),"","", listOf(),0,true, creationDate = LocalDate.now(), type = 0, globalId = UUID.randomUUID()))
    val selectedWorkout: State<Workout> get() = _selectedWorkout

    private lateinit var workoutRecordDao: WorkoutRecordDao

    private lateinit var workoutHistoryDao: WorkoutHistoryDao

    private lateinit var setHistoryDao: SetHistoryDao

    private lateinit var exerciseInfoDao: ExerciseInfoDao

    private lateinit var workoutStoreRepository: WorkoutStoreRepository

    private val _workoutState = MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()

    private val _nextWorkoutState = MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val nextWorkoutState = _nextWorkoutState.asStateFlow()

    public val executedSetsHistory: MutableList<SetHistory> = mutableListOf()

    private val heartBeatHistory: ConcurrentLinkedQueue<Int> = ConcurrentLinkedQueue()

    private val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    private val workoutStateHistory: MutableList<WorkoutState> = mutableListOf()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    private val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    public val latestSetHistoryMap: MutableMap<UUID, SetHistory> = mutableMapOf()

    val distributedWorkoutByExerciseIdMap: MutableMap<UUID, Pair<VolumeDistributionHelper.DistributedWorkout?,Boolean>?> = mutableMapOf()

    private var currentWorkoutHistory by mutableStateOf<WorkoutHistory?>(null)

    private var startWorkoutTime by mutableStateOf<LocalDateTime?> (null)

    val exercisesById : Map<UUID, Exercise> get() = selectedWorkout.value.workoutComponents
        .filterIsInstance<Exercise>()
        .associateBy { it.id }

    val setsByExerciseId: Map<UUID, List<WorkoutState.Set>> get () = setStates
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

    fun setWorkout(workout: Workout){
        _selectedWorkout.value = workout;

        _hasExercises.value =
            selectedWorkout.value.workoutComponents.filter { it.enabled }.isNotEmpty()

        getWorkoutRecord(workout)
    }

    fun resetAll(){
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                workoutHistoryDao.deleteAll()
                setHistoryDao.deleteAll()
                exerciseInfoDao.deleteAll()
            }
        }
    }

    fun sendAll(context: Context){
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                val statuses = mutableListOf<Boolean>()
                val workouts = workoutStore.workouts.filter { it.enabled && it.isActive }

                if(workouts.isEmpty()) return@withContext

                workouts.forEach {
                    val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(it.id) ?: return@forEach
                    val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                    val exercises= it.workoutComponents.filterIsInstance<Exercise>()
                    val exerciseInfos = exercises.mapNotNull { exercise -> exerciseInfoDao.getExerciseInfoById(exercise.id) }

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

                if(statuses.contains(false)){
                    withContext(Dispatchers.Main){
                        Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                    }
                }else{
                    withContext(Dispatchers.Main){
                        Toast.makeText(context, "Data sent to phone", Toast.LENGTH_SHORT).show()
                    }
                }

            }
        }
    }

    private fun getWorkoutRecord(workout: Workout){
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                _workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
                _hasWorkoutRecord.value = _workoutRecord != null
            }
        }
    }

    fun upsertWorkoutRecord(setId: UUID){
        viewModelScope.launch(Dispatchers.IO) {
            if(_workoutRecord == null) {
                _workoutRecord = WorkoutRecord(
                    id = UUID.randomUUID(),
                    workoutId = selectedWorkout.value.id,
                    setId = setId,
                    workoutHistoryId = currentWorkoutHistory!!.id
                )
            }else{
                _workoutRecord = _workoutRecord!!.copy(
                    setId = setId,
                )
            }

            workoutRecordDao.insert(_workoutRecord!!)

            _hasWorkoutRecord.value = true
        }
    }

    fun deleteWorkoutRecord(){
        viewModelScope.launch(Dispatchers.IO) {
            _workoutRecord?.let {
                workoutRecordDao.deleteById(it.id)
                _workoutRecord = null
                _hasWorkoutRecord.value = false
            }
        }
    }

    fun resumeWorkoutFromRecord(onEnd: () -> Unit = {}){
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
                workoutStateQueue.clear()
                workoutStateHistory.clear()
                _isHistoryEmpty.value = workoutStateHistory.isEmpty()
                setStates.clear()
                executedSetsHistory.clear()
                currentWorkoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(_workoutRecord!!.workoutHistoryId,false)
                heartBeatHistory.addAll(currentWorkoutHistory!!.heartBeatRecords)
                startWorkoutTime = currentWorkoutHistory!!.startTime
                loadWorkoutHistory()
                generateProgressions()
                generateWorkoutStates()
                workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)

                _workoutRecord = null
                onEnd()
            }
        }
    }

    private suspend fun generateProgressions() = coroutineScope {
        distributedWorkoutByExerciseIdMap.clear()

        val exerciseWithWeightSets = selectedWorkout.value.workoutComponents
            .filter { it.enabled && it is Exercise && (it.exerciseType == ExerciseType.WEIGHT || it.exerciseType == ExerciseType.BODY_WEIGHT) }
            .filterIsInstance<Exercise>()

        // Launch parallel processing for each exercise
        val deferredResults = exerciseWithWeightSets.map { exercise ->
            async {
                processExercise(exercise)
            }
        }

        // Await all results and collect them into the map
        deferredResults.awaitAll().forEach { result ->
            result?.let { (exerciseId, distribution) ->
                distributedWorkoutByExerciseIdMap[exerciseId] = distribution
            }
        }
    }

    // Helper function to process a single exercise
    private suspend fun processExercise(exercise: Exercise): Pair<UUID,Pair<DistributedWorkout?,Boolean>>? {
        val exerciseSets = exercise.sets.filter { it !is RestSet }
        val restSetCount = exerciseSets
            .zipWithNext()
            .count { (previous, current) ->
                previous is RestSet && previous.isRestPause && current !is RestSet
            }

        val totalHistoricalSetDataList = when(exercise.exerciseType) {
            ExerciseType.WEIGHT -> getHistoricalSetsDataByExerciseId<WeightSetData>(exercise.id)
            ExerciseType.BODY_WEIGHT -> getHistoricalSetsDataByExerciseId<BodyWeightSetData>(exercise.id)
            else -> emptyList()
        }

        if (totalHistoricalSetDataList.isEmpty()) return null

        val lastTotalVolume = totalHistoricalSetDataList.sumOf {
            when(it) {
                is BodyWeightSetData -> it.actualReps.toDouble()
                is WeightSetData -> calculateVolume(it.actualWeight, it.actualReps).toDouble()
                else -> 0.0
            }
        }

        val avg1RM = getAverageOneRepMaxByExerciseId(exercise.id)

        when(exercise.exerciseType) {
            ExerciseType.WEIGHT -> {
                if(lastTotalVolume == 0.0 || avg1RM == 0.0) return null
            }
            ExerciseType.BODY_WEIGHT -> {
                if(lastTotalVolume == 0.0) return null
            }
            else -> throw IllegalArgumentException("Unknown exercise type")
        }

        val distributedWorkout = when(exercise.exerciseType) {
            ExerciseType.WEIGHT -> VolumeDistributionHelper.distributeVolumeWithMinimumIncrease(
                exerciseSets.size - restSetCount,
                lastTotalVolume,
                avg1RM,
                0.5,
                exercise.volumeIncreasePercent,
                Pair(exercise.minLoadPercent, exercise.maxLoadPercent),
                IntRange(exercise.minReps, exercise.maxReps),
                exercise.fatigueFactor
            )
            ExerciseType.BODY_WEIGHT -> VolumeDistributionHelper.distributeBodyWeightVolumeWithMinimumIncrease(
                exerciseSets.size - restSetCount,
                lastTotalVolume,
                exercise.volumeIncreasePercent,
                IntRange(exercise.minReps, exercise.maxReps),
                exercise.fatigueFactor
            )
            else -> throw IllegalArgumentException("Unknown exercise type")
        }

        return exercise.id to distributedWorkout
    }

    fun resumeLastState(){
        if(_workoutRecord == null) return

        val targetSetId = _workoutRecord!!.setId
        if (_workoutState.value is WorkoutState.Set && (_workoutState.value as WorkoutState.Set).set.id == targetSetId) {
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _isResuming.value = true
            while (_workoutState.value !is WorkoutState.Finished) {
                goToNextState()

                if (_workoutState.value is WorkoutState.Set && (_workoutState.value as WorkoutState.Set).set.id == targetSetId) {
                    break
                }
            }
            delay(2000)
            _isResuming.value = false
        }
    }

    fun startWorkout(){
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
                workoutStateQueue.clear()
                workoutStateHistory.clear()
                _isHistoryEmpty.value = workoutStateHistory.isEmpty()
                setStates.clear()
                executedSetsHistory.clear()
                heartBeatHistory.clear()
                startWorkoutTime = null
                currentWorkoutHistory = null
                loadWorkoutHistory()
                generateProgressions()
                generateWorkoutStates()
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
            }
        }
    }

    fun sendWorkoutHistoryToPhone(onEnd: (Boolean) -> Unit = {}){
        viewModelScope.launch(Dispatchers.IO) {
            val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)
            if(workoutHistory == null){
                withContext(Dispatchers.Main){
                    onEnd(false)
                }
                return@launch
            }

            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

            val exerciseInfos = selectedWorkout.value.workoutComponents.filter { it is Exercise }.mapNotNull {
                val exercise = it as Exercise
                exerciseInfoDao.getExerciseInfoById(exercise.id)
            }

            dataClient?.let {
                sendWorkoutHistoryStore(
                    it,WorkoutHistoryStore(
                        WorkoutHistory = workoutHistory,
                        SetHistories =  setHistories,
                        ExerciseInfos = exerciseInfos
                    ))
            }

            withContext(Dispatchers.Main){
                onEnd(true)
            }
        }
    }

    private suspend fun loadWorkoutHistory(){
        val workoutHistories = workoutHistoryDao
            .getAllWorkoutHistories()
            .filter { it.globalId == selectedWorkout.value.globalId && it.isDone }
            .sortedByDescending { it.date }

        val exercises = selectedWorkout.value.workoutComponents.filterIsInstance<Exercise>()

        val calledIndexes = mutableListOf<Int>()

        exercises.filter { !it.doNotStoreHistory }.forEach { exercise ->
            var workoutHistoryIndex = 0;

            while(workoutHistoryIndex < workoutHistories.size){
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(workoutHistories[workoutHistoryIndex].id,exercise.id)
                if(setHistories.isNotEmpty()){
                    for(setHistory in setHistories) {
                        latestSetHistoryMap[setHistory.setId] = setHistory
                    }

                    if (!calledIndexes.contains(workoutHistoryIndex)) {
                        calledIndexes.add(workoutHistoryIndex)
                    }

                    break
                }else{
                    workoutHistoryIndex++
                }
            }
        }

        val neverCalledWorkoutHistories = workoutHistories.filterIndexed { index, _ -> index !in calledIndexes }

        neverCalledWorkoutHistories.forEach {
            workoutHistoryDao.deleteById(it.id)
        }
    }

    fun registerHeartBeat(heartBeat: Int){
        if(heartBeat > 0) heartBeatHistory.add(heartBeat)
    }

    private fun updateWorkout(currentExercise: Exercise,updatedExercise: Exercise){
        val updatedComponents = updateWorkoutComponentsRecursively(_selectedWorkout.value.workoutComponents, currentExercise, updatedExercise)
        _selectedWorkout.value = _selectedWorkout.value.copy(workoutComponents = updatedComponents)

        val currentWorkoutStore = workoutStoreRepository.getWorkoutStore()
        val newWorkoutStore = currentWorkoutStore.copy(workouts = currentWorkoutStore.workouts.map {
            if(it.id == _selectedWorkout.value.id){
                it.copy(workoutComponents = updatedComponents)
            }else{
                it
            }
        })

        workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
        updateWorkoutStore(newWorkoutStore)
    }

    fun addNewSetStandard(){
        if (_workoutState.value !is WorkoutState.Set) return
        val currentState = _workoutState.value as WorkoutState.Set

        val currentSetIndex = exercisesById[currentState.exerciseId]!!.sets.indexOf(currentState.set)
        val currentExercise =  exercisesById[currentState.exerciseId]!!

        val newSets = currentExercise.sets.toMutableList()
        val newRestSet = RestSet(UUID.randomUUID(),90)
        newSets.add(currentSetIndex + 1,newRestSet)
        val newSet = getNewSet(currentState.set)
        newSets.add(currentSetIndex + 2,newSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise,updatedExercise)

        RefreshAndGoToNextState()
    }

    fun addNewRest(){
        if (_workoutState.value !is WorkoutState.Set) return
        val currentState = _workoutState.value as WorkoutState.Set

        val currentSetIndex = exercisesById[currentState.exerciseId]!!.sets.indexOf(currentState.set)
        val currentExercise =  exercisesById[currentState.exerciseId]!!

        val newSets = currentExercise.sets.toMutableList()
        val newRestSet = RestSet(UUID.randomUUID(),90)
        newSets.add(currentSetIndex + 1,newRestSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise,updatedExercise)

        RefreshAndGoToNextState()
    }

    fun addNewRestPauseSet(){
        if (_workoutState.value !is WorkoutState.Set) return
        val currentState = _workoutState.value as WorkoutState.Set
        if (currentState.set !is BodyWeightSet && currentState.set !is WeightSet) return

        val currentSetIndex = exercisesById[currentState.exerciseId]!!.sets.indexOf(currentState.set)
        val currentExercise = exercisesById[currentState.exerciseId]!!

        val newSets = currentExercise.sets.toMutableList()
        val newRestSet = RestSet(UUID.randomUUID(),20,true)
        newSets.add(currentSetIndex + 1,newRestSet)
        val newSet = when(val new = getNewSet(currentState.set)){
            is BodyWeightSet ->  new.copy(reps = 3)
            is WeightSet -> new.copy(reps = 3)
            else -> throw IllegalArgumentException("Unknown set type")
        }
        newSets.add(currentSetIndex + 2,newSet)

        val updatedExercise = currentExercise.copy(sets = newSets)
        updateWorkout(currentExercise,updatedExercise)

        RefreshAndGoToNextState()
    }

    private fun RefreshAndGoToNextState(){
        viewModelScope.launch(Dispatchers.IO) {
            if(_isRefreshing.value || (_workoutState.value !is WorkoutState.Set && _workoutState.value !is WorkoutState.Rest)) return@launch

            _isRefreshing.value = true

            workoutStateQueue.clear()
            workoutStateHistory.clear()
            _isHistoryEmpty.value = workoutStateHistory.isEmpty()
            setStates.clear()

            generateWorkoutStates()
            workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))

            val targetSetId = when(_workoutState.value){
                is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                else -> throw RuntimeException("Invalid state")
            }

            _workoutState.value = workoutStateQueue.pollFirst()!!

            while (_workoutState.value !is WorkoutState.Finished) {
                val currentSetId = when(_workoutState.value){
                    is WorkoutState.Set -> (_workoutState.value as WorkoutState.Set).set.id
                    is WorkoutState.Rest -> (_workoutState.value as WorkoutState.Rest).set.id
                    else -> throw RuntimeException("Invalid state")
                }

                if (currentSetId == targetSetId) {
                    break
                }

                goToNextState()
            }

            if(_workoutState.value !is WorkoutState.Finished){
                goToNextState()
            }

            _isRefreshing.value = false
        }
    }

    fun pushAndStoreWorkoutData(isDone: Boolean, context: Context? = null,forceNotSend: Boolean = false, onEnd: () -> Unit = {}) {
        viewModelScope.launch(Dispatchers.IO) {
            val duration = Duration.between(startWorkoutTime!!, LocalDateTime.now())

            if(currentWorkoutHistory == null){
                currentWorkoutHistory = WorkoutHistory(
                    id = UUID.randomUUID(),
                    workoutId= selectedWorkout.value.id,
                    date = LocalDate.now(),
                    duration = duration.seconds.toInt(),
                    heartBeatRecords = heartBeatHistory.toList(),
                    time = LocalTime.now(),
                    startTime = startWorkoutTime!!,
                    isDone = isDone,
                    hasBeenSentToHealth = false,
                    globalId = selectedWorkout.value.globalId
                )
            }else{
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

            if(isDone){
                val exerciseHistories = executedSetsHistory.groupBy { it.exerciseId }

                val filteredExerciseHistories = exerciseHistories.filter { it.value.any { it.setData is BodyWeightSetData || it.setData is WeightSetData } }

                filteredExerciseHistories.forEach{
                    val setDataList = it.value.filter { setHistory -> setHistory.setData !is RestSetData }.map { setHistory -> setHistory.setData }
                    val firstSetData = setDataList.first()

                    val volume = when(firstSetData){
                        is BodyWeightSetData -> {
                            setDataList.sumOf {item -> (item as BodyWeightSetData).actualReps }.toDouble()
                        }
                        is WeightSetData -> {
                            setDataList.sumOf { item ->
                                val weightSetData = item as WeightSetData
                                calculateVolume(weightSetData.actualWeight, weightSetData.actualReps).toDouble()
                            }
                        }
                        else -> throw IllegalArgumentException("Unknown set type")
                    }

                    val avgOneRepMax = if(firstSetData is WeightSetData){
                        setDataList.sumOf { item ->
                            val weightSetData = item as WeightSetData
                            calculateOneRepMax(weightSetData.actualWeight, weightSetData.actualReps).toDouble()
                        } / setDataList.size
                    }else{
                        0.0
                    }

                    val exerciseInfo = exerciseInfoDao.getExerciseInfoById(it.key!!)

                    if(exerciseInfo == null){
                        val newExerciseInfo = ExerciseInfo(
                            id = it.key!!,
                            bestVolume = volume,
                            avgOneRepMax = avgOneRepMax
                        )
                        exerciseInfoDao.insert(newExerciseInfo)
                        exerciseInfos.add(newExerciseInfo)
                    }else{
                        if(exerciseInfo.bestVolume < volume){
                            exerciseInfoDao.updateBestVolume(it.key!!,volume)
                        }

                        if(exerciseInfo.avgOneRepMax < avgOneRepMax){
                            exerciseInfoDao.updateAvgOneRepMax(it.key!!,avgOneRepMax)
                        }

                        exerciseInfos.add(exerciseInfo)
                    }
                }
            }

            val currentState = _workoutState.value
            val shouldSendData = currentState != setStates.last() || isDone

            if(forceNotSend || !shouldSendData){
                onEnd()
                return@launch
            }

            withContext(Dispatchers.IO){
                val result = sendWorkoutHistoryStore(
                    dataClient!!,
                    WorkoutHistoryStore(
                        WorkoutHistory = currentWorkoutHistory!!,
                        SetHistories =  executedSetsHistory,
                        ExerciseInfos = exerciseInfos
                    )
                )

                if(context != null && !result){
                    withContext(Dispatchers.Main){
                        Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                    }
                }

                withContext(Dispatchers.Main){
                    onEnd()
                }
            }
        }
    }

    suspend fun getBestVolumeByExerciseId(exerciseId: UUID): Double{
        return exerciseInfoDao.getExerciseInfoById(exerciseId)?.bestVolume ?: 0.0
    }

    suspend fun getAverageOneRepMaxByExerciseId(exerciseId: UUID): Double{
        return exerciseInfoDao.getExerciseInfoById(exerciseId)?.avgOneRepMax ?: 0.0
    }

    fun storeSetData() {
        val currentState = _workoutState.value
        if (!(currentState is WorkoutState.Set || currentState is WorkoutState.Rest)) return

        if(currentState is WorkoutState.Set){
            val exercise = exercisesById[currentState.exerciseId]!!
            if(exercise.doNotStoreHistory) return
        }

        val newSetHistory = when(currentState){
            is WorkoutState.Set ->SetHistory(
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
        val existingIndex = when(currentState){
            is WorkoutState.Set -> executedSetsHistory.indexOfFirst { it.setId == currentState.set.id && it.order == currentState.order }
            is WorkoutState.Rest ->  executedSetsHistory.indexOfFirst { it.setId == currentState.set.id && it.order == currentState.order }
            else -> return
        }
        if (existingIndex != -1) {
            executedSetsHistory[existingIndex] = newSetHistory.copy(id = executedSetsHistory[existingIndex].id, version = executedSetsHistory[existingIndex].version.inc())
        } else {
            // If not found, add the new entry
            executedSetsHistory.add(newSetHistory)
        }
    }

    inline fun <reified T : SetData> getAllExecutedSetsDataByExerciseId(exerciseId: UUID): List<T> {
        return executedSetsHistory
            .filter { it.exerciseId == exerciseId }
            .mapNotNull { it.setData as? T }
    }

    inline fun <reified T : SetData> getExecutedSetsDataByExerciseIdAndTakeUntilSetId(exerciseId: UUID, setId: UUID): List<T> {
        return executedSetsHistory
            .filter { it.exerciseId == exerciseId }
            .takeWhile { it.setId != setId }
            .plus(executedSetsHistory.filter{  it.exerciseId == exerciseId && it.id == setId })
            .mapNotNull { it.setData as? T }
    }

    inline fun <reified T : SetData> getHistoricalSetsDataByExerciseId(exerciseId: UUID): List<T> {
        if(exercisesById[exerciseId]!!.doNotStoreHistory) return emptyList()
        return exercisesById[exerciseId]!!.sets.filter { latestSetHistoryMap.contains(it.id) && latestSetHistoryMap[it.id]!!.setData is T }.map{ latestSetHistoryMap[it.id]!!.setData as T }
    }

    inline fun <reified T : SetData> getHistoricalSetsDataByExerciseIdAndTakeUntilSetId(exerciseId: UUID, setId: UUID): List<T> {
        if(exercisesById[exerciseId]!!.doNotStoreHistory) return emptyList()
        return exercisesById[exerciseId]!!.sets
            .filter { it !is RestSet }
            .takeWhile { it.id != setId }
            .plus(exercisesById[exerciseId]!!.sets.filter { it !is RestSet && it.id == setId })
            .filter { latestSetHistoryMap.contains(it.id) }
            .map { latestSetHistoryMap[it.id]!!.setData as T }

    }

    private fun generateWorkoutStates() {
        val workoutComponents = selectedWorkout.value.workoutComponents.filter { it.enabled }
        for ((index, workoutComponent) in workoutComponents.withIndex()) {
            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent)
                is Rest -> {
                    val restSet = RestSet(workoutComponent.id,workoutComponent.timeInSeconds)

                    val restState = WorkoutState.Rest(
                        set = restSet,
                        order = index.toUInt(),
                        currentSetData = initializeSetData(RestSet(workoutComponent.id,workoutComponent.timeInSeconds))
                    )
                    workoutStateQueue.addLast(restState)
                }
            }
        }
    }

    private fun addStatesFromExercise(exercise: Exercise){
        if(exercise.sets.isEmpty()) return

        var currentExercise = exercise
        val distributedWorkout = if(distributedWorkoutByExerciseIdMap.containsKey(exercise.id)) distributedWorkoutByExerciseIdMap[exercise.id] else null

        if(distributedWorkout != null){
            if(distributedWorkout.first != null){
                val distributedSets = distributedWorkout.first!!.sets
                val restSets = exercise.sets.filterIsInstance<RestSet>()
                val lastRestSet = restSets.lastOrNull()

                val exerciseSets = currentExercise.sets.filter { it !is RestSet }

                for ((index, setInfo) in distributedSets.withIndex()) {
                    if (index < exerciseSets.size) continue

                    val newSets = currentExercise.sets.toMutableList()

                    if(lastRestSet!=null){
                        val newRestSet = RestSet(UUID.randomUUID(),lastRestSet.timeInSeconds)
                        newSets.add(newRestSet)
                    }

                    val newSet = when(currentExercise.exerciseType){
                        ExerciseType.BODY_WEIGHT -> BodyWeightSet(UUID.randomUUID(),setInfo.reps)
                        ExerciseType.WEIGHT -> WeightSet(UUID.randomUUID(),setInfo.reps, setInfo.weight.toFloat())
                        else -> throw IllegalArgumentException("Unknown exercise type")
                    }

                    newSets.add(newSet)
                    currentExercise = currentExercise.copy(sets = newSets)
                    updateWorkout(currentExercise,currentExercise)
                }
            }

            if(distributedWorkout.second){
                val newSets = currentExercise.sets.toMutableList()
                val newRestSet = RestSet(UUID.randomUUID(),20,true)
                newSets.add(newRestSet)

                val newSet = when(val new = getNewSet(currentExercise.sets.last())){
                    is BodyWeightSet ->  new.copy(reps = 3)
                    is WeightSet -> new.copy(reps = 3)
                    else -> throw IllegalArgumentException("Unknown set type")
                }

                newSets.add(newSet)
                currentExercise = currentExercise.copy(sets = newSets)
                updateWorkout(currentExercise,currentExercise)
            }
        }

        var exerciseIndex = 0

        for ((index, set) in currentExercise.sets.withIndex()) {
            if(set is RestSet){
                val restSet = RestSet(set.id,set.timeInSeconds)

                val restState = WorkoutState.Rest(
                    set = restSet,
                    order = index.toUInt(),
                    currentSetData = initializeSetData(RestSet(set.id,set.timeInSeconds)),
                    exerciseId = currentExercise.id
                )
                workoutStateQueue.addLast(restState)
            }else{
                val historySet = if(currentExercise.doNotStoreHistory) null else latestSetHistoryMap[set.id];

                var currentSetData = initializeSetData(set)

                if(historySet != null && distributedWorkout == null){
                    val historySetData = historySet.setData
                    if(isSetDataValid(set,historySetData)){
                        currentSetData = historySet.setData
                    }
                }else if(distributedWorkout != null && distributedWorkout.first != null){
                    val distributedSet = distributedWorkout.first!!.sets[exerciseIndex]
                    currentSetData = when(currentExercise.exerciseType){
                        ExerciseType.BODY_WEIGHT -> BodyWeightSetData(
                            actualReps = distributedSet.reps,
                        )
                        ExerciseType.WEIGHT -> WeightSetData(
                            actualReps = distributedSet.reps,
                            actualWeight = distributedSet.weight.toFloat(),
                        )
                        else -> throw IllegalArgumentException("Unknown exercise type")
                    }
                }

                val previousSetData = copySetData(currentSetData)
                val setState: WorkoutState.Set = WorkoutState.Set(currentExercise.id,set,index.toUInt(),previousSetData, currentSetData,historySet == null,false)
                workoutStateQueue.addLast(setState)
                setStates.addLast(setState)
                exerciseIndex++
            }
        }
    }

    fun setWorkoutStart(){
        val startTime = LocalDateTime.now()
        startWorkoutTime = startTime
        workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))
    }

    fun goToNextState(){
        if (workoutStateQueue.isEmpty()) return

        if(_workoutState.value !is WorkoutState.Preparing){
            workoutStateHistory.add(_workoutState.value)
            _isHistoryEmpty.value = workoutStateHistory.isEmpty()
        }

        val newState = workoutStateQueue.pollFirst()!!
        if (workoutStateQueue.isNotEmpty()) _nextWorkoutState.value = workoutStateQueue.peek()!!
        _workoutState.value = newState
    }

    fun goToPreviousSet() {
        if (workoutStateHistory.isEmpty() || (workoutStateHistory.size ==1 && workoutStateHistory[0] ===_workoutState.value)) return

        // Remove the current state from the queue and re-add it at the beginning to revisit later
        val currentState = _workoutState.value
        workoutStateQueue.addFirst(currentState)

        // Any state in the workoutStateQueue that was skipped (beyond the current state)
        // should now be placed back at the front of the queue to ensure they are the next targets.
        // This step may vary based on how you want to handle the reordering.
        // Assuming you want to reverse the order of "future" states so they are encountered in the original order:
        while (workoutStateHistory.isNotEmpty()) {
            val skippedState = workoutStateHistory.removeAt(workoutStateHistory.size - 1)

            if(skippedState is WorkoutState.Set){
                _workoutState.value = skippedState
                break
            }

            workoutStateQueue.addFirst(skippedState)
        }

        // Update the next workout state based on the new queue
        _nextWorkoutState.value = workoutStateQueue.peek()!!
        _isHistoryEmpty.value = workoutStateHistory.isEmpty()
    }

    fun skipExercise(){
        val currentState =  _workoutState.value as WorkoutState.Set
        val currentExerciseId = currentState.exerciseId

        while(workoutStateQueue.isNotEmpty()){
            val state = workoutStateQueue.pollFirst()

            if(state is WorkoutState.Set){
                val stateExerciseId = state.exerciseId
                if(stateExerciseId != currentExerciseId){
                    _workoutState.value = state
                    break
                }
            }

            if(state is WorkoutState.Finished){
                _workoutState.value = state
                break
            }
        }
    }
}