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
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.isSetDataValid
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Node
import kotlinx.coroutines.Dispatchers
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
        val parentExercise: Exercise,
        var set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val order: Int,
        val previousSetData: SetData?,
        var currentSetData:  SetData,
        val hasNoHistory: Boolean,
        var skipped: Boolean
    ) : WorkoutState()
    data class Rest(
        val restTimeInSec: Int,
    ) : WorkoutState()
    data class Finished(val startWorkoutTime:LocalDateTime) : WorkoutState()
}

class AppViewModel : ViewModel(){
    private var workoutStore by mutableStateOf(
            WorkoutStore(
                workouts = emptyList(),
                polarDeviceId = null,
                birthDateYear = 0
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

    private val _selectedWorkout = mutableStateOf(Workout(java.util.UUID.randomUUID(),"","", listOf(),0,0, creationDate = LocalDate.now(), globalId = UUID.randomUUID()))
    val selectedWorkout: State<Workout> get() = _selectedWorkout

    private lateinit var workoutRecordDao: WorkoutRecordDao

    private lateinit var workoutHistoryDao: WorkoutHistoryDao

    private lateinit var setHistoryDao: SetHistoryDao

    private val _workoutState = MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()

    private val _nextWorkoutState = MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val nextWorkoutState = _nextWorkoutState.asStateFlow()

    private val executedSetsHistory: MutableList<SetHistory> = mutableListOf()

    private val heartBeatHistory: ConcurrentLinkedQueue<Int> = ConcurrentLinkedQueue()

    private val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    private val workoutStateHistory: MutableList<WorkoutState> = mutableListOf()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    private val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    private val latestSetHistoryMap: MutableMap<UUID, SetHistory> = mutableMapOf()

    private var currentWorkoutHistory by mutableStateOf<WorkoutHistory?>(null)

    private var startWorkoutTime by mutableStateOf<LocalDateTime?> (null)

    val setsByExercise: Map<Exercise, List<WorkoutState.Set>> get () = setStates
        .groupBy { it.parentExercise }

    private var _workoutRecord by mutableStateOf<WorkoutRecord?>(null)

    private val _isResuming = MutableStateFlow<Boolean>(false)
    val isResuming = _isResuming.asStateFlow()

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
                generateWorkoutStates()
                workoutStateQueue.addLast(WorkoutState.Finished(startWorkoutTime!!))
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)

                _workoutRecord = null
                onEnd()
            }
        }
    }

    fun resumeLastState(){
        if(_workoutRecord == null) return

        _isResuming.value = true
        val targetSetId = _workoutRecord!!.setId

        if (_workoutState.value is WorkoutState.Set && (_workoutState.value as WorkoutState.Set).set.id == targetSetId) {
            _isResuming.value = false
            return
        }

        while (_workoutState.value !is WorkoutState.Finished) {
            goToNextState()

            if (_workoutState.value is WorkoutState.Set && (_workoutState.value as WorkoutState.Set).set.id == targetSetId) {
                break
            }
        }
        _isResuming.value = false
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
                generateWorkoutStates()
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
            }
        }
    }

    fun sendWorkoutHistoryToPhone(onEnd: (Boolean) -> Unit = {}){
        viewModelScope.launch(Dispatchers.Main) {
            val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)
            if(workoutHistory !=null){
                val exerciseHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

                dataClient?.let {
                    sendWorkoutHistoryStore(
                        it,WorkoutHistoryStore(
                            WorkoutHistory = workoutHistory,
                            ExerciseHistories =  exerciseHistories
                        ))
                }
                onEnd(true)
            }else{
                onEnd(false)
            }
        }
    }

    private suspend fun loadWorkoutHistory(){
        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)
        latestSetHistoryMap.clear()
        if(workoutHistory !=null){
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
            for(setHistory in setHistories){
                latestSetHistoryMap[setHistory.setId] = setHistory
            }
        }
    }

    fun registerHeartBeat(heartBeat: Int){
        if(heartBeat > 0) heartBeatHistory.add(heartBeat)
    }

    fun pushAndStoreWorkoutData(isDone: Boolean, context: Context? = null, onEnd: () -> Unit = {}) {
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
                    isDone = isDone
                )

                workoutHistoryDao.deleteAllByWorkoutId(selectedWorkout.value.id)
                workoutHistoryDao.insert(currentWorkoutHistory!!)
            }else{
                currentWorkoutHistory = currentWorkoutHistory!!.copy(
                    duration = duration.seconds.toInt(),
                    heartBeatRecords = heartBeatHistory.toList(),
                    time = LocalTime.now(),
                    isDone = isDone
                )

                workoutHistoryDao.insert(currentWorkoutHistory!!)
            }

            executedSetsHistory.forEach { it.workoutHistoryId = currentWorkoutHistory!!.id }
            setHistoryDao.insertAll(*executedSetsHistory.toTypedArray())

            val currentState = _workoutState.value
            val shouldSendData = !(currentState == setStates.last && !isDone)

            if(shouldSendData){
                withContext(Dispatchers.Main){
                    val result = sendWorkoutHistoryStore(
                        dataClient!!,
                        WorkoutHistoryStore(
                            WorkoutHistory = currentWorkoutHistory!!,
                            ExerciseHistories =  executedSetsHistory
                        )
                    )

                    if(context != null && !result){
                        Toast.makeText(context, "Failed to send data to phone", Toast.LENGTH_SHORT).show()
                    }
                }
            }

            onEnd()
        }
    }

    fun storeSetData() {
        val currentState = _workoutState.value
        if (currentState !is WorkoutState.Set) return
        if(currentState.parentExercise.doNotStoreHistory) return

        val newSetHistory = SetHistory(
            id = UUID.randomUUID(),
            setId = currentState.set.id,
            setData = currentState.currentSetData,
            order = currentState.order,
            exerciseId = currentState.parentExercise.id,
            skipped = currentState.skipped
        )

        // Search for an existing entry in the history
        val existingIndex = executedSetsHistory.indexOfFirst { it.setId == currentState.set.id && it.order == currentState.order }

        if (existingIndex != -1) {
            // If found, replace the existing entry
            executedSetsHistory[existingIndex] = newSetHistory
        } else {
            // If not found, add the new entry
            executedSetsHistory.add(newSetHistory)
        }
    }

    private fun generateWorkoutStates() {
        val workoutComponents = selectedWorkout.value.workoutComponents.filter { it.enabled }
        for ((index, workoutComponent) in workoutComponents.withIndex()) {
            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent)
                is ExerciseGroup -> addStatesFromExerciseGroup(workoutComponent)
            }

            if (selectedWorkout.value.restTimeInSec > 0 && index < workoutComponents.size - 1 && !workoutComponent.skipWorkoutRest) {
                workoutStateQueue.addLast(WorkoutState.Rest(selectedWorkout.value.restTimeInSec))
            }
        }
    }

    private fun addStatesFromExercise(exercise: Exercise){
        for ((index, set) in exercise.sets.withIndex()) {
            val historySet = if(exercise.doNotStoreHistory) null else latestSetHistoryMap[set.id];
            Log.d("AppViewModel", "History set: $historySet doNotStoreHistory: ${exercise.doNotStoreHistory}")

            var currentSet = initializeSetData(set)

            if(historySet != null){
                val historySetData = historySet.setData
                if(isSetDataValid(set,historySetData)){
                    currentSet = historySet.setData
                }
            }

            val previousSet = copySetData(currentSet)

            val setState: WorkoutState.Set = WorkoutState.Set(exercise,set,index,previousSet, currentSet,historySet == null,false)
            workoutStateQueue.addLast(setState)
            setStates.addLast(setState)

            if (exercise.restTimeInSec >0 && index < exercise.sets.size - 1) {
                workoutStateQueue.addLast(WorkoutState.Rest(exercise.restTimeInSec))
            }
        }
    }

    private fun addStatesFromExerciseGroup(exerciseGroup: ExerciseGroup){
        val workoutComponents = exerciseGroup.workoutComponents.filter { it.enabled }
        for ((index, workoutComponent) in workoutComponents.withIndex()) {
            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent)
                is ExerciseGroup -> addStatesFromExerciseGroup(workoutComponent)
            }

            if (exerciseGroup.restTimeInSec > 0 && index < workoutComponents.size - 1 && !workoutComponent.skipWorkoutRest) {
                workoutStateQueue.addLast(WorkoutState.Rest(exerciseGroup.restTimeInSec))
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
}