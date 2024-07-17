package com.gabstra.myworkoutassistant

import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Calendar
import java.util.UUID

sealed class ScreenData() {
    class Workouts(val selectedTabIndex : Int) : ScreenData()
    class Settings() : ScreenData()
    class NewWorkout() : ScreenData()
    class EditWorkout(val workoutId: UUID) : ScreenData()
    class WorkoutDetail(val workoutId: UUID) : ScreenData()
    class WorkoutHistory(val workoutId: UUID,val workoutHistoryId: UUID? = null) : ScreenData()
    class ExerciseGroupDetail(val workoutId: UUID, val selectedExerciseGroupId: UUID) : ScreenData()
    class ExerciseDetail(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()
    class ExerciseHistory(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()
    class NewExerciseGroup(val workoutId: UUID, val parentExerciseGroupId: UUID?) : ScreenData()
    class EditExerciseGroup(val workoutId: UUID, val selectedExerciseGroupId: UUID) : ScreenData()
    class NewExercise(val workoutId: UUID, val parentExerciseGroupId: UUID?) : ScreenData()
    class EditExercise(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()
    class NewSet(val workoutId: UUID, val parentExerciseId: UUID) : ScreenData()
    class EditSet(val workoutId: UUID, val selectedSet: Set, val parentExerciseId: UUID) : ScreenData()
}


class AppViewModel() : ViewModel() {
    private var screenDataStack = mutableListOf<ScreenData>(ScreenData.Workouts(0))

    // Convert currentScreenData to a MutableState
    var currentScreenData: ScreenData by mutableStateOf(screenDataStack.lastOrNull() ?: ScreenData.Workouts(0))
        private set

    private var _userAge = mutableIntStateOf(0)
    val userAge: State<Int> = _userAge

    private val _updateNotificationFlow = MutableStateFlow<String?>(null)
    val updateNotificationFlow = _updateNotificationFlow.asStateFlow()

    var selectedHomeTab by mutableIntStateOf(0)
        private set

    fun notifyUpdateReceived() {
        _updateNotificationFlow.value = System.currentTimeMillis().toString()
    }

    fun setHomeTab(tabIndex: Int) {
        selectedHomeTab = tabIndex
    }

    fun setScreenData(screenData: ScreenData,skipStack: Boolean = false) {
        currentScreenData = screenData
        if(!skipStack){
            screenDataStack.add(screenData)
        }
    }

    //function to update current screen data
    fun updateScreenData(screenData: ScreenData) {
        currentScreenData = screenData
        screenDataStack[screenDataStack.size - 1] = screenData
    }

    fun goBack(): Boolean {
        if (screenDataStack.size > 1) {
            screenDataStack.removeAt(screenDataStack.size - 1)
            currentScreenData = screenDataStack.last()
            return true
        } else if (screenDataStack.size == 1) {
            // Handle the case where stack size is 1
            // You can perform some action here if needed
            return false
        }
        return false
    }
    var workoutStore by mutableStateOf(WorkoutStore(
        workouts = emptyList(),
        polarDeviceId = null,
        birthDateYear = 0
    ))
        private set

    private val _workoutsFlow = MutableStateFlow(workoutStore.workouts)
    val workoutsFlow = _workoutsFlow.asStateFlow()

    var workouts: List<Workout>
        get() = workoutStore.workouts
        private set(value) {
            _workoutsFlow.value = value
            workoutStore = workoutStore.copy(workouts = value)
        }



    fun updateWorkoutStore(newWorkoutStore: WorkoutStore) {
        workoutStore = newWorkoutStore
        val currentYear = Calendar.getInstance().get(Calendar.YEAR)
        _userAge.intValue =  currentYear - workoutStore.birthDateYear
        _workoutsFlow.value = newWorkoutStore.workouts
    }

    fun updateWorkouts(newWorkouts: List<Workout>) {
        workouts = newWorkouts
    }

    fun updateWorkoutOld(oldWorkout: Workout, updatedWorkout: Workout) {
        workouts = WorkoutManager.updateWorkoutOld(workouts,oldWorkout,updatedWorkout)
    }


    fun updateWorkout(oldWorkout: Workout, updatedWorkout: Workout) {
        workouts = WorkoutManager.updateWorkout(workouts,oldWorkout,updatedWorkout)
    }

    fun updateWorkoutComponent(parentWorkout: Workout, oldWorkoutComponent: WorkoutComponent, updatedWorkoutComponent: WorkoutComponent) {
        workouts = WorkoutManager.updateWorkoutComponent(workouts,parentWorkout,oldWorkoutComponent,updatedWorkoutComponent)
    }

    fun addNewWorkout(newWorkout: Workout) {
        workouts = workouts + newWorkout.copy(order = workouts.size)
    }

    fun addWorkoutComponent(workout: Workout, newWorkoutComponent: WorkoutComponent) {
        workouts = WorkoutManager.addWorkoutComponent(workouts,workout,newWorkoutComponent)
    }

    fun addWorkoutComponentToExerciseGroup(workout: Workout, exerciseGroup: ExerciseGroup, newWorkoutComponent: WorkoutComponent) {
        workouts = WorkoutManager.addWorkoutComponentToExerciseGroup(workouts,workout,exerciseGroup,newWorkoutComponent)
    }

    fun addSetToExercise(workout: Workout, exercise: Exercise, newSet: Set) {
        workouts = WorkoutManager.addSetToExercise(workouts,workout,exercise,newSet)
    }

    fun updateSetInExercise(workout: Workout, exercise: Exercise, oldSet:Set,updatedSet: Set) {
        workouts = WorkoutManager.updateSetInExercise(workouts,workout,exercise,oldSet,updatedSet)
    }

    fun deleteWorkout(workoutToDelete: Workout) {
        workouts = workouts.filter { it != workoutToDelete }  // Direct object comparison
    }

    fun deleteWorkoutComponent(workout: Workout, workoutComponentToDelete: WorkoutComponent) {
        workouts = WorkoutManager.deleteWorkoutComponent(workouts,workout,workoutComponentToDelete)
    }

    fun deleteSet(workout: Workout, exercise: Exercise, setToDelete: Set) {
        workouts = WorkoutManager.deleteSet(workouts,workout,exercise,setToDelete)
    }
}
