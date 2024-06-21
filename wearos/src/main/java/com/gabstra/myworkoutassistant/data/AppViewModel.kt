package com.gabstra.myworkoutassistant.data

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
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
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
        setHistoryDao= db.setHistoryDao()
    }

    fun initWorkoutHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        workoutHistoryDao= db.workoutHistoryDao()
    }

    private val _selectedWorkout = mutableStateOf(Workout(java.util.UUID.randomUUID(),"","", listOf(),0, creationDate = LocalDate.now()))
    val selectedWorkout: State<Workout> get() = _selectedWorkout

    private lateinit var workoutHistoryDao: WorkoutHistoryDao

    private lateinit var setHistoryDao: SetHistoryDao

    private val _workoutState = MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState = _workoutState.asStateFlow()

    private val _nextWorkoutState = MutableStateFlow<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val nextWorkoutState = _nextWorkoutState.asStateFlow()

    private val executedSetsHistory: MutableList<SetHistory> = mutableListOf()

    private val heartBeatHistory: MutableList<Int> = mutableListOf()

    private val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    private val workoutStateHistory: MutableList<WorkoutState> = mutableListOf()

    private val _isHistoryEmpty = MutableStateFlow<Boolean>(true)
    val isHistoryEmpty = _isHistoryEmpty.asStateFlow()

    private val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    private val latestSetHistoryMap: MutableMap<UUID, SetHistory> = mutableMapOf()

    val setsByExercise: Map<Exercise, List<WorkoutState.Set>> get () = setStates
        .groupBy { it.parentExercise }

    fun setWorkout(workout: Workout){
        _selectedWorkout.value = workout;
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
                loadWorkoutHistory()
                generateWorkoutStates()
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
            }
        }
    }

    fun sendWorkoutHistoryToPhone(){
        viewModelScope.launch {
            val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(selectedWorkout.value.id)
            if(workoutHistory !=null){
                val exerciseHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

                dataClient?.let {
                    sendWorkoutHistoryStore(
                        it,WorkoutHistoryStore(
                            WorkoutHistory =workoutHistory,
                            ExerciseHistories =  exerciseHistories
                        ))
                }
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
        heartBeatHistory.add(heartBeat)
    }

    fun endWorkout(duration: Duration, onEnd: () -> Unit = {}) {
        viewModelScope.launch {
            val newWorkoutHistory =  WorkoutHistory(
                workoutId= selectedWorkout.value.id,
                date = LocalDate.now(),
                duration = duration.seconds.toInt(),
                heartBeatRecords = heartBeatHistory,
                time = LocalTime.now()
            )

            val workoutHistoryId = workoutHistoryDao.insert(newWorkoutHistory).toInt()
            executedSetsHistory.forEach { it.workoutHistoryId = workoutHistoryId }
            setHistoryDao.insertAll(*executedSetsHistory.toTypedArray())

            dataClient?.let {
                sendWorkoutHistoryStore(
                    it,WorkoutHistoryStore(
                        WorkoutHistory = newWorkoutHistory,
                        ExerciseHistories =  executedSetsHistory
                    ))
            }

            executedSetsHistory.clear()

            onEnd()
        }
    }

    fun storeExecutedSetHistory(state: WorkoutState.Set) {
        val newSetHistory = SetHistory(
            setId = state.set.id,
            setData = state.currentSetData,
            order = state.order,
            exerciseId = state.parentExercise.id,
            skipped = state.skipped
        )

        // Search for an existing entry in the history
        val existingIndex = executedSetsHistory.indexOfFirst { it.setId == state.set.id && it.order == state.order }

        if (existingIndex != -1) {
            // If found, replace the existing entry
            executedSetsHistory[existingIndex] = newSetHistory
        } else {
            // If not found, add the new entry
            executedSetsHistory.add(newSetHistory)
        }
    }

    private fun generateWorkoutStates() {
        for ((index, workoutComponent) in selectedWorkout.value.workoutComponents.withIndex()) {
            if(!workoutComponent.enabled) continue

            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent)
                is ExerciseGroup -> addStatesFromExerciseGroup(workoutComponent)
            }

            if (selectedWorkout.value.restTimeInSec >0 && index < selectedWorkout.value.workoutComponents.size - 1 && !workoutComponent.skipWorkoutRest) {
                workoutStateQueue.addLast(WorkoutState.Rest(selectedWorkout.value.restTimeInSec))
            }
        }
    }

    private fun addStatesFromExercise(exercise: Exercise){
        for ((index, set) in exercise.sets.withIndex()) {
            val historySet = latestSetHistoryMap[set.id];

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
        for ((index, workoutComponent) in exerciseGroup.workoutComponents.withIndex()) {
            if(!workoutComponent.enabled) continue

            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent)
                is ExerciseGroup -> addStatesFromExerciseGroup(workoutComponent)
            }

            if (exerciseGroup.restTimeInSec >0 && index < exerciseGroup.workoutComponents.size - 1) {
                workoutStateQueue.addLast(WorkoutState.Rest(selectedWorkout.value.restTimeInSec))
            }
        }
    }

    fun setWorkoutStart(){
        workoutStateQueue.addLast(WorkoutState.Finished(LocalDateTime.now()))
    }

    fun goToNextState(){
        if (workoutStateQueue.isEmpty()) return

        if(_workoutState.value !is WorkoutState.Preparing){
            workoutStateHistory.add(_workoutState.value)
            _isHistoryEmpty.value = workoutStateHistory.isEmpty()
        }

        _workoutState.value = workoutStateQueue.pollFirst()!!
        if (workoutStateQueue.isNotEmpty()) _nextWorkoutState.value = workoutStateQueue.peek()!!
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