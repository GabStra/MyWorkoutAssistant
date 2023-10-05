package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.shared.Exercise

@Composable
fun ExerciseContent(exercise: Exercise){
    Row (
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = Modifier
            .fillMaxWidth().padding(15.dp)
    ){
        Text(
            modifier = Modifier.weight(2f),
            text = exercise.name
        )
        Column( modifier = Modifier.weight(1f)) {
            Text(
                text = "Reps: ${exercise.reps}"
            )
            Spacer(modifier=Modifier.height(5.dp))
            Text(
                text = if(exercise.weight != null) "${exercise.weight} kg" else "Body-weight"
            )
        }
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseGroupDetailScreen(
    navController: NavController,
    appViewModel: AppViewModel,
    workoutId: Int,
    exerciseGroupId : Int,
    onGoBack : () -> Unit
) {
    val selectedWorkout = appViewModel.workouts[workoutId]
    val selectedExerciseGroup = selectedWorkout.exerciseGroups[exerciseGroupId]

    val exercises = selectedExerciseGroup.exercises

    var selectedExercises by remember { mutableStateOf(setOf<Exercise>()) }
    var selectionMode by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(selectedExerciseGroup.name) },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        navController.navigate(Screen.getRoute(Screen.EditExerciseGroup,workoutId,exerciseGroupId))
                    }) {
                        Icon(imageVector = Icons.Default.Settings, contentDescription = "Back")
                    }
                }
            )
        },
        bottomBar = {
            if(selectedExercises.isNotEmpty()) BottomAppBar(
                actions =  {
                    IconButton(onClick = {
                        val newExercises = exercises.filter { exercise->
                            exercise !in selectedExercises
                        }

                        val updatedExerciseGroup  = selectedExerciseGroup.copy(exercises = newExercises)
                        appViewModel.updateExerciseGroup(selectedWorkout,selectedExerciseGroup,updatedExerciseGroup)
                        selectedExercises = emptySet()
                        selectionMode = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (exercise in selectedExercises) {
                                appViewModel.updateExercise(selectedWorkout,selectedExerciseGroup,exercise,exercise.copy(enabled = true))
                            }
                            selectedExercises = emptySet()
                            selectionMode = false
                        }) {
                        Text("Enable")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (exercise in selectedExercises) {
                                appViewModel.updateExercise(selectedWorkout,selectedExerciseGroup,exercise,exercise.copy(enabled = false))
                            }
                            selectedExercises = emptySet()
                            selectionMode = false
                        }) {
                        Text("Disable")
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedExercises.isEmpty())
                FloatingActionButton(
                    onClick = {
                        navController.navigate(Screen.getRoute(Screen.NewExercise,workoutId,exerciseGroupId))
                    }
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null
                    )
                }
        }
    ) {
        if(exercises.isEmpty()){
            Text(modifier = Modifier.padding(it).fillMaxSize(),text = "Add a new exercise", textAlign = TextAlign.Center)
        }else{
            SelectableList(
                selectionMode,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .clickable {
                        if (selectionMode) {
                            selectionMode = false
                            selectedExercises= emptySet()
                        }
                    },
                items = exercises,
                selection = selectedExercises,
                onSelectionChange = { newSelection -> selectedExercises = newSelection} ,
                itemContent = { it ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (it.enabled) 1f else 0.4f)
                            .combinedClickable(
                                onClick = {
                                    if (selectionMode) {
                                        val newSelection =
                                            if (selectedExercises.contains(it)) {
                                                selectedExercises - it
                                            } else {
                                                selectedExercises + it
                                            }
                                        selectedExercises = newSelection
                                    } else {
                                        val exerciseId = exercises.indexOf(it)
                                        navController.navigate(Screen.getRoute(Screen.EditExercise,workoutId,exerciseGroupId,exerciseId))
                                    }
                                },
                                onLongClick = { if (!selectionMode) selectionMode = true }
                            ),

                        ) {
                        ExerciseContent(it)
                    }
                },
            )
        }
    }
}