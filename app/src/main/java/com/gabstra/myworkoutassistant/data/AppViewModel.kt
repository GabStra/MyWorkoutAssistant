package com.gabstra.myhomeworkoutassistant.data

import android.content.Context
import android.util.Log
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.Exercise
import com.gabstra.myworkoutassistant.shared.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.ExerciseHistory
import com.gabstra.myworkoutassistant.shared.ExerciseHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.LinkedList

sealed class WorkoutState {
    object Preparing : WorkoutState()
    object Warmup : WorkoutState()
    data class Exercise(
        val exerciseGroup: ExerciseGroup,
        val exercise: com.gabstra.myworkoutassistant.shared.Exercise,
        val currentSet: Int,
        val reps: Int,
        val weight : Float?
    ) : WorkoutState()
    data class Rest(
        val restTimeInSec: Int,
    ) : WorkoutState()
    data class Finished(val startWorkoutTime:LocalDateTime) : WorkoutState()
}

class AppViewModel : ViewModel(){
    var workouts by mutableStateOf(emptyList<Workout>())
        private set

    fun updateWorkouts(newWorkouts: List<Workout>) {
        workouts = newWorkouts
    }

    private val _selectedWorkout = mutableStateOf(Workout("","", listOf(),0))
    val selectedWorkout: State<Workout> get() = _selectedWorkout


    private lateinit var workoutHistoryDao: WorkoutHistoryDao

    private lateinit var exerciseHistoryDao: ExerciseHistoryDao

    private val _workoutState = mutableStateOf<WorkoutState>(WorkoutState.Preparing)
    val workoutState: State<WorkoutState> get() = _workoutState

    private val _nextWorkoutState = mutableStateOf<WorkoutState>(WorkoutState.Preparing)
    val nextWorkoutState: State<WorkoutState> get() = _nextWorkoutState


    private val executedExercisesHistory: MutableList<ExerciseHistory> = mutableListOf()

    private val workoutStateQueue: LinkedList<WorkoutState> = LinkedList()

    private val latestExerciseHistoryMap: MutableMap<Pair<String, Int>, ExerciseHistory> = mutableMapOf()


    fun setWorkout(workout: Workout){
        _selectedWorkout.value = workout;
        executedExercisesHistory.clear()
    }

    fun startWorkout(){
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                _workoutState.value=WorkoutState.Preparing
                var startLoadingTime= LocalDateTime.now()
                loadWorkoutHistory()
                generateWorkoutStates()
                var interval = Duration.between(startLoadingTime, LocalDateTime.now())
                var intervalInMillis = interval.toMillis()
                if(intervalInMillis<1000) delay(1000-intervalInMillis)
                _workoutState.value=WorkoutState.Warmup
            }
        }
    }

    private suspend fun loadWorkoutHistory(){
        val workout = workoutHistoryDao.getLatestWorkoutHistoryByName(selectedWorkout.value.name)
        latestExerciseHistoryMap.clear()
        if(workout !=null){
            val exerciseHistories = exerciseHistoryDao.getExerciseHistoriesByWorkoutHistoryId(workout.id)
            for(exerciseHistory in exerciseHistories){
                latestExerciseHistoryMap[Pair(exerciseHistory.name,exerciseHistory.set)] = exerciseHistory
            }
        }
    }

    fun endWorkout(onEnd: () -> Unit = {}) {
        viewModelScope.launch {
            withContext(Dispatchers.IO){
                val existingWorkouts = workoutHistoryDao.getWorkoutsByNameAndDate(selectedWorkout.value.name,LocalDate.now())

                if(existingWorkouts.isNotEmpty()){
                    for(workout in existingWorkouts){
                        workoutHistoryDao.deleteById(workout.id)
                    }
                }

                val workoutHistoryId = workoutHistoryDao.insert(
                    WorkoutHistory(
                    name= selectedWorkout.value.name,
                    date = LocalDate.now()
                )
                ).toInt()
                executedExercisesHistory.forEach { it.workoutHistoryId = workoutHistoryId }
                exerciseHistoryDao.insertAll(*executedExercisesHistory.toTypedArray())
                executedExercisesHistory.clear()
            }
            onEnd()
        }
    }

    fun storeExecutedExerciseHistory(executedReps: Int, usedWeightsInKGs : Float?, skipped:Boolean = false){
        if (workoutState.value is WorkoutState.Exercise) {
            val exerciseState = workoutState.value as WorkoutState.Exercise
            val newExerciseHistory = ExerciseHistory(
                name = exerciseState.exercise.name,
                set = exerciseState.currentSet,
                reps = executedReps,
                weight = usedWeightsInKGs,
                skipped = skipped
            )

            executedExercisesHistory.add(newExerciseHistory)
        }
    }

    private fun getStartingRepsAndWeight(exercise: Exercise, set:Int): Pair<Int, Float?> {
        val key = Pair(exercise.name, set)
        val history = latestExerciseHistoryMap[key]
        if(history != null){
            return Pair(history.reps,history.weight)
        }

        return Pair(exercise.reps,exercise.weight)
    }

    private fun generateWorkoutStates() {
        workoutStateQueue.clear()
        for ((groupIndex, exerciseGroup) in selectedWorkout.value.exerciseGroups.withIndex()) {
            repeat(exerciseGroup.sets) { setIndex ->
                for (exercise in exerciseGroup.exercises) {
                    val (reps, weight) = getStartingRepsAndWeight(exercise, setIndex + 1)
                    workoutStateQueue.addLast(WorkoutState.Exercise(exerciseGroup, exercise, setIndex + 1, reps, weight))
                }
                if (setIndex < exerciseGroup.sets - 1) {
                    workoutStateQueue.addLast(WorkoutState.Rest(exerciseGroup.restTimeInSec))
                }
            }
            if (groupIndex < selectedWorkout.value.exerciseGroups.size - 1) {
                workoutStateQueue.addLast(WorkoutState.Rest(selectedWorkout.value.restTimeInSec))
            }
        }
        workoutStateQueue.addLast(WorkoutState.Finished(LocalDateTime.now()))
    }



    fun goToNextState(){
        if (workoutStateQueue.isEmpty()) return
        _workoutState.value = workoutStateQueue.pollFirst()!!
        if (workoutStateQueue.isNotEmpty()) _nextWorkoutState.value = workoutStateQueue.peek()!!
    }

    fun initExerciseHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        exerciseHistoryDao= db.exerciseHistoryDao()
    }

    fun initWorkoutHistoryDao(context: Context){
        val db = AppDatabase.getDatabase(context)
        workoutHistoryDao= db.workoutHistoryDao()
    }
}