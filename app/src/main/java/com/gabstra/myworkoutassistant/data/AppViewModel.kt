package com.gabstra.myhomeworkoutassistant.data

import android.content.Context
import android.util.Log
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.data.sendWorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryStore
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.wearable.DataClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.LinkedList

sealed class WorkoutState {
    data class Preparing (
        val dataLoaded :Boolean
    ): WorkoutState()
    data class Set(
        val parents: List<WorkoutComponent>,
        val exerciseName: String,
        val set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val setHistoryId : String,
        val previousSetData: SetData?,
        var currentSetData:  SetData,
        var skipped: Boolean
    ) : WorkoutState()
    data class Rest(
        val restTimeInSec: Int,
    ) : WorkoutState()
    data class Finished(val startWorkoutTime:LocalDateTime) : WorkoutState()
}

class AppViewModel : ViewModel(){
    var workouts by mutableStateOf(emptyList<Workout>())
        private set

    private var dataClient: DataClient? = null

    fun updateWorkouts(newWorkouts: List<Workout>) {
        workouts = newWorkouts
    }

    fun initDataClient(client: DataClient) {
        dataClient = client
    }

    private val _selectedWorkout = mutableStateOf(Workout("","", listOf(),0))
    val selectedWorkout: State<Workout> get() = _selectedWorkout

    private lateinit var workoutHistoryDao: WorkoutHistoryDao

    private lateinit var setHistoryDao: SetHistoryDao

    private val _workoutState = mutableStateOf<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val workoutState: State<WorkoutState> get() = _workoutState

    private val _nextWorkoutState = mutableStateOf<WorkoutState>(WorkoutState.Preparing(dataLoaded = false))
    val nextWorkoutState: State<WorkoutState> get() = _nextWorkoutState


    private val executedSetsHistory: MutableList<SetHistory> = mutableListOf()

    private val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    private val setStates: LinkedList<WorkoutState.Set> = LinkedList()

    private val latestSetHistoryMap: MutableMap<String, SetHistory> = mutableMapOf()

    val groupedSets: Map<WorkoutComponent?, List<WorkoutState.Set>> get () = setStates
        .groupBy { it.parents.firstOrNull() }

    fun setWorkout(workout: Workout){
        _selectedWorkout.value = workout;
        executedSetsHistory.clear()
    }

    fun startWorkout(){
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                _workoutState.value = WorkoutState.Preparing(dataLoaded = false)
                workoutStateQueue.clear()
                setStates.clear()
                loadWorkoutHistory()
                generateWorkoutStates()
                _workoutState.value = WorkoutState.Preparing(dataLoaded = true)
            }
        }
    }

    private suspend fun loadWorkoutHistory(){
        val workout = workoutHistoryDao.getLatestWorkoutHistoryByName(selectedWorkout.value.name)
        latestSetHistoryMap.clear()
        if(workout !=null){
            val exerciseHistories = setHistoryDao.getExerciseHistoriesByWorkoutHistoryId(workout.id)
            for(exerciseHistory in exerciseHistories){
                latestSetHistoryMap[exerciseHistory.setHistoryId] = exerciseHistory
            }
        }
    }

    fun endWorkout(onEnd: () -> Unit = {}) {
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                val existingWorkouts = workoutHistoryDao.getWorkoutsByName(selectedWorkout.value.name)

                if(existingWorkouts.isNotEmpty()){
                    for(workout in existingWorkouts){
                        workoutHistoryDao.deleteById(workout.id)
                        setHistoryDao.deleteByWorkoutHistoryId(workout.id)
                    }
                }

                val workoutHistoryId = workoutHistoryDao.insert(
                    WorkoutHistory(
                    name= selectedWorkout.value.name,
                    date = LocalDate.now()
                )
                ).toInt()
                executedSetsHistory.forEach { it.workoutHistoryId = workoutHistoryId }
                setHistoryDao.insertAll(*executedSetsHistory.toTypedArray())
                executedSetsHistory.clear()
            }
            dataClient?.let {
                sendWorkoutHistoryStore(
                    it,WorkoutHistoryStore(
                        WorkoutHistory = WorkoutHistory(
                            name= selectedWorkout.value.name,
                            date = LocalDate.now()
                        ),
                        ExerciseHistories =  executedSetsHistory
                    ))
            }
            onEnd()
        }
    }

    fun storeExecutedSetHistory(state: WorkoutState.Set){
        val newSetHistory = SetHistory(
            setHistoryId = state.setHistoryId,
            setData = state.currentSetData,
            skipped = state.skipped
        )

        executedSetsHistory.add(newSetHistory)
    }

    private fun generateWorkoutStates() {

        for ((index, workoutComponent) in selectedWorkout.value.workoutComponents.withIndex()) {
            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent, listOf(index),listOf(workoutComponent))
                is ExerciseGroup -> addStatesFromExerciseGroup(workoutComponent,listOf(index),listOf(workoutComponent))
            }

            if (selectedWorkout.value.restTimeInSec >0 && index < selectedWorkout.value.workoutComponents.size - 1 && !workoutComponent.skipWorkoutRest) {
                workoutStateQueue.addLast(WorkoutState.Rest(selectedWorkout.value.restTimeInSec))
            }
        }
        workoutStateQueue.addLast(WorkoutState.Finished(LocalDateTime.now()))
    }

    private fun addStatesFromExercise(exercise: Exercise, idList: List<Int>, parentsList:List<WorkoutComponent>){
        for ((index, set) in exercise.sets.withIndex()) {
            val setHistoryId = (idList+index).joinToString(separator = "-")
            val historySet = latestSetHistoryMap[setHistoryId];
            val currentSet = historySet?.setData
                ?: when(set){
                    is WeightSet -> WeightSetData(set.reps,set.weight)
                    is BodyWeightSet -> BodyWeightSetData(set.reps)
                    is TimedDurationSet -> TimedDurationSetData(0)
                    is EnduranceSet -> EnduranceSetData(0)
                }

            val previousSet = when(currentSet){
                is WeightSetData -> currentSet.copy()
                is BodyWeightSetData -> currentSet.copy()
                is TimedDurationSetData -> currentSet.copy()
                is EnduranceSetData -> currentSet.copy()
            }

            val setState: WorkoutState.Set = WorkoutState.Set(parentsList + exercise,exercise.name,set,setHistoryId,previousSet, currentSet,false)
            workoutStateQueue.addLast(setState)
            setStates.addLast(setState)
            if (exercise.restTimeInSec >0 && index < exercise.sets.size - 1) {
                workoutStateQueue.addLast(WorkoutState.Rest(exercise.restTimeInSec))
            }
        }
    }

    private fun addStatesFromExerciseGroup(exerciseGroup: ExerciseGroup, idList: List<Int>, parentsList:List<WorkoutComponent>){
        for ((index, workoutComponent) in exerciseGroup.workoutComponents.withIndex()) {
            when(workoutComponent){
                is Exercise -> addStatesFromExercise(workoutComponent, idList+ index,parentsList + exerciseGroup)
                is ExerciseGroup -> addStatesFromExerciseGroup(workoutComponent,idList + index,parentsList + exerciseGroup)
            }

            if (exerciseGroup.restTimeInSec >0 && index < exerciseGroup.workoutComponents.size - 1) {
                workoutStateQueue.addLast(WorkoutState.Rest(selectedWorkout.value.restTimeInSec))
            }
        }
    }

    fun goToNextState(){
        if (workoutStateQueue.isEmpty()) return
        _workoutState.value = workoutStateQueue.pollFirst()!!
        if (workoutStateQueue.isNotEmpty()) _nextWorkoutState.value = workoutStateQueue.peek()!!
    }

    fun initExerciseHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        setHistoryDao= db.setHistoryDao()
    }

    fun initWorkoutHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        workoutHistoryDao= db.workoutHistoryDao()
    }
}