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
import androidx.compose.material3.Card
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
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.ExerciseGroupRenderer
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.composables.GenericFloatingActionButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

@Composable
fun SetRenderer(set: Set){
    Row (
        modifier = Modifier.padding(15.dp),
    ){
        when(set){
            is WeightSet ->{
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        modifier = Modifier.weight(1f),
                        text = "Reps: ${set.reps}"
                    )
                    Text(
                        modifier = Modifier.weight(1f),
                        text = "Weight: ${set.weight}kg"
                    )
                }
            }
            is BodyWeightSet -> {
                Text(
                    text = "Reps: ${set.reps}"
                )
            }
            is EnduranceSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "Time: ${set.timeInMillis/1000}s"
                )
            }
            is TimedDurationSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "Time: ${set.timeInMillis/1000}s"
                )
            }
        }
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseGroupDetailScreen(
    navController: NavController,
    appViewModel: AppViewModel,
    workout: Workout,
    exercise: Exercise,
    parentExerciseGroup: ExerciseGroup?,
    onGoBack : () -> Unit
){
    val sets = exercise.sets
    var selectedSets by remember { mutableStateOf(setOf<com.gabstra.myworkoutassistant.shared.sets.Set>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(exercise.name) },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        appViewModel.setScreenData(
                            ScreenData.EditExercise(
                                workout,
                                exercise
                            )
                        );
                        navController.navigate(ScreenData.EDIT_EXERCISE_ROUTE)
                    }) {
                        Icon(imageVector = Icons.Default.Settings, contentDescription = "Back")
                    }
                }
            )
        },
        bottomBar = {
            if(selectedSets.isNotEmpty()) BottomAppBar(
                actions =  {
                    IconButton(onClick = {
                        val newSets = sets.filter {
                            it !in selectedSets
                        }

                        val updatedExercise = exercise.copy(sets = newSets)

                        appViewModel.updateWorkoutComponents(workout,exercise,updatedExercise)
                        selectedSets = emptySet()
                        isSelectionModeActive = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedSets.isEmpty()){
                FloatingActionButton(
                    onClick = {
                        appViewModel.setScreenData(ScreenData.NewSet(workout,exercise));
                        navController.navigate(ScreenData.NEW_SET_ROUTE)
                    }
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null
                    )
                }
            }
        },
    ) { it ->
        if(sets.isEmpty()){
            Text(modifier = Modifier
                .padding(it)
                .fillMaxSize(),text = "Add a new set", textAlign = TextAlign.Center)
        }else{
            GenericSelectableList(
                it,
                items = sets,
                selectedItems= selectedSets,
                isSelectionModeActive,
                onItemClick = {
                    appViewModel.setScreenData(ScreenData.EditSet(workout, it,exercise))
                    navController.navigate(ScreenData.EDIT_SET_ROUTE)
                },
                onEnableSelection = { isSelectionModeActive = true },
                onDisableSelection = { isSelectionModeActive = false },
                onSelectionChange = { newSelection -> selectedSets = newSelection} ,
                itemContent = { it ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                    ){
                        SetRenderer(it)
                    }
                }
            )
        }
    }
}