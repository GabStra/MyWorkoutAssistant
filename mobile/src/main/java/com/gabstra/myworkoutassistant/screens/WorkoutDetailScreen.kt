package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.ExerciseGroupRenderer
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.GenericFloatingActionButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale


@Composable
fun WorkoutComponentTitle(modifier:Modifier, workoutComponent: WorkoutComponent){
    Row (
        horizontalArrangement = Arrangement.End,
        modifier=modifier.padding(15.dp),
    ){
        Text(
            modifier = Modifier.weight(2.7f),
            text = workoutComponent.name
        )
    }
}


@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutDetailScreen(
    navController: NavController,
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workout: Workout,
    onGoBack : () -> Unit
) {
    val workoutComponents = workout.workoutComponents

    var selectedWorkoutComponents by remember { mutableStateOf(setOf<WorkoutComponent>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    val formatter = remember { DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy", Locale.ENGLISH)}
    val workoutHistoryDates = remember { mutableStateOf(listOf<LocalDate>()) }

    LaunchedEffect(workout) {
        withContext(Dispatchers.IO) {
            val dates = workoutHistoryDao.getWorkoutsByNameByDateAsc(workout.name)
                .map { it -> it.date }
            workoutHistoryDates.value = dates
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(workout.name) },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        appViewModel.setScreenData(ScreenData.EditWorkout(workout));
                        navController.navigate(ScreenData.EDIT_WORKOUT_ROUTE)
                    }) {
                        Icon(imageVector = Icons.Default.Settings, contentDescription = "Back")
                    }
                }
            )
        },
        bottomBar = {
            if(selectedWorkoutComponents.isNotEmpty()) BottomAppBar(
                actions =  {
                    IconButton(onClick = {
                        val newWorkoutComponents = workoutComponents.filter {
                            it !in selectedWorkoutComponents
                        }

                        val updatedWorkout = workout.copy(workoutComponents = newWorkoutComponents)
                        appViewModel.updateWorkout(workout,updatedWorkout)
                        selectedWorkoutComponents = emptySet()
                        isSelectionModeActive = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (workoutComponent in selectedWorkoutComponents) {
                                val updatedWorkoutComponent = when(workoutComponent){
                                    is Exercise -> workoutComponent.copy(enabled = true)
                                    is ExerciseGroup -> workoutComponent.copy(enabled = true)
                                }

                                appViewModel.updateWorkoutComponents(workout,workoutComponent,updatedWorkoutComponent)
                            }
                            selectedWorkoutComponents = emptySet()
                            isSelectionModeActive = false
                        }) {
                        Text("Enable")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (workoutComponent in selectedWorkoutComponents)  {
                                val updatedWorkoutComponent = when(workoutComponent){
                                    is Exercise -> workoutComponent.copy(enabled = true)
                                    is ExerciseGroup -> workoutComponent.copy(enabled = true)
                                }
                                appViewModel.updateWorkoutComponents(workout,workoutComponent,updatedWorkoutComponent)
                            }
                            selectedWorkoutComponents = emptySet()
                            isSelectionModeActive = false
                        }) {
                        Text("Disable")
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedWorkoutComponents.isEmpty())
                GenericFloatingActionButtonWithMenu(
                    menuItems = listOf(
                        MenuItem("Add Exercise") {
                            appViewModel.setScreenData(ScreenData.NewExercise(workout, null));
                            navController.navigate(ScreenData.NEW_EXERCISE_ROUTE)
                        },
                        MenuItem("Add Exercise Group") {
                            appViewModel.setScreenData(ScreenData.NewExerciseGroup(workout, null));
                            navController.navigate(ScreenData.NEW_EXERCISE_GROUP_ROUTE)
                        }

                    ),
                    fabIcon = { Icon(Icons.Filled.Add, contentDescription = "Add") }
                )
        },
    ) { it ->


        if(workoutComponents.isEmpty()){
            Text(modifier = Modifier
                .padding(it)
                .fillMaxSize(),text = "Add a new workout component", textAlign = TextAlign.Center)
        }else{
            if(workoutHistoryDates.value.isNotEmpty()){
                Text(modifier = Modifier
                    .padding(it)
                    .fillMaxSize(),
                    text = "Last executed ${workoutHistoryDates.value.last().format(formatter)}",
                    textAlign = TextAlign.Center
                )
            }
            GenericSelectableList(
                it,
                items = workoutComponents,
                selectedItems= selectedWorkoutComponents,
                isSelectionModeActive,
                onItemClick = {
                    when(it){
                        is Exercise -> {
                            appViewModel.setScreenData(ScreenData.ExerciseDetail(workout, it,null))
                            navController.navigate(ScreenData.EXERCISE_DETAIL_ROUTE)
                        }
                        is ExerciseGroup ->{
                            appViewModel.setScreenData(ScreenData.ExerciseGroupDetail(workout, it,null))
                            navController.navigate(ScreenData.EXERCISE_GROUP_DETAIL_ROUTE)
                        }
                    }
                },
                onEnableSelection = { isSelectionModeActive = true },
                onDisableSelection = { isSelectionModeActive = false },
                onSelectionChange = { newSelection -> selectedWorkoutComponents = newSelection} ,
                itemContent = { it ->
                    ExpandableCard(
                        isExpandable = when(it) {
                                is Exercise -> it.sets.isNotEmpty()
                                is ExerciseGroup -> it.workoutComponents.isNotEmpty()
                                else -> false
                            },
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (it.enabled) 1f else 0.4f),
                        title = { modifier -> WorkoutComponentTitle(modifier,it) },
                        content = { when(it) {
                            is Exercise -> ExerciseRenderer(it)
                            is ExerciseGroup -> ExerciseGroupRenderer(it)
                        } }
                    )
                }
            )
        }
    }
}