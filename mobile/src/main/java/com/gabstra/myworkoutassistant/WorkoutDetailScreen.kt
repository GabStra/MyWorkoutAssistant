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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale


@Composable
fun ExerciseGroupTitle(modifier:Modifier,exerciseGroup: ExerciseGroup){
    Row (
        horizontalArrangement = Arrangement.End,
        modifier=modifier.padding(15.dp),
    ){
        Text(
            modifier = Modifier.weight(2.7f),
            text = exerciseGroup.name
        )
        Text(
            modifier = Modifier.weight(.3f),
            text = "(${exerciseGroup.exercises.size})"
        )
    }
}

@Composable
fun ExerciseGroupContent(exerciseGroup: ExerciseGroup){
    Card(
        modifier=Modifier.padding(15.dp)
    ){
    Spacer(modifier=Modifier.height(15.dp))
    for(exercise in exerciseGroup.exercises){
        Row (horizontalArrangement = Arrangement.SpaceBetween,
            modifier = Modifier.fillMaxWidth()){
            Text(
                modifier = Modifier.weight(1f),
                text = exercise.name
            )
            Column( horizontalAlignment = Alignment.End)  {
                Text(
                    text = "Reps: ${exercise.reps}"
                )
                Spacer(modifier=Modifier.height(5.dp))
                Text(
                    text = if(exercise.weight != null) "${exercise.weight} kg" else "Body-weight"
                )
            }
        }
        if(exercise != exerciseGroup.exercises.last()) Divider( modifier = Modifier
            .fillMaxWidth()
            .padding(10.dp),thickness = 1.dp, color = Color.White)
    }
    Spacer(modifier=Modifier.height(10.dp))
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutDetailScreen(
    navController: NavController,
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutId: Int,
    onGoBack : () -> Unit
) {
    val selectedWorkout = appViewModel.workouts[workoutId]
    val exerciseGroups = selectedWorkout.exerciseGroups
    var selectedExerciseGroups by remember { mutableStateOf(setOf<ExerciseGroup>()) }
    var selectionMode by remember { mutableStateOf(false) }
    val formatter = remember { DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy", Locale.ENGLISH)}
    val workoutHistoryDates = remember { mutableStateOf(listOf<LocalDate>()) }

    LaunchedEffect(selectedWorkout) {
        withContext(Dispatchers.IO) {
            val dates = workoutHistoryDao.getWorkoutsByNameByDateAsc(selectedWorkout.name)
                .map { it -> it.date }
            workoutHistoryDates.value = dates
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(selectedWorkout.name) },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        navController.navigate(Screen.getRoute(Screen.EditWorkout,workoutId))
                    }) {
                        Icon(imageVector = Icons.Default.Settings, contentDescription = "Back")
                    }
                }
            )
        },
        bottomBar = {
            if(selectedExerciseGroups.isNotEmpty()) BottomAppBar(
                actions =  {
                    IconButton(onClick = {
                        val newExerciseGroups = exerciseGroups.filter { exerciseGroup ->
                            exerciseGroup !in selectedExerciseGroups
                        }

                        val updatedWorkout = selectedWorkout.copy(exerciseGroups = newExerciseGroups)
                        appViewModel.updateWorkout(selectedWorkout,updatedWorkout)
                        selectedExerciseGroups = emptySet()
                        selectionMode = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (exerciseGroup in selectedExerciseGroups) {
                                appViewModel.updateExerciseGroup(selectedWorkout,exerciseGroup,exerciseGroup.copy(enabled = true))
                            }
                            selectedExerciseGroups = emptySet()
                            selectionMode = false
                        }) {
                        Text("Enable")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (exerciseGroup in selectedExerciseGroups) {
                                appViewModel.updateExerciseGroup(selectedWorkout,exerciseGroup,exerciseGroup.copy(enabled = false))
                            }
                            selectedExerciseGroups = emptySet()
                            selectionMode = false
                        }) {
                        Text("Disable")
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedExerciseGroups.isEmpty())
                FloatingActionButton(
                    onClick = {
                        navController.navigate(Screen.getRoute(Screen.NewExerciseGroup,workoutId))
                    }
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null
                    )
                }
        },
    ) { it ->


        if(exerciseGroups.isEmpty()){
            Text(modifier = Modifier
                .padding(it)
                .fillMaxSize(),text = "Add a new exercise group", textAlign = TextAlign.Center)
        }else{
            if(workoutHistoryDates.value.isNotEmpty()){
                Text(modifier = Modifier
                    .padding(it)
                    .fillMaxSize(),
                    text = "Last executed ${workoutHistoryDates.value.last().format(formatter)}",
                    textAlign = TextAlign.Center
                )
            }
            SelectableList(
                selectionMode,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .clickable {
                        if (selectionMode) {
                            selectionMode = false
                            selectedExerciseGroups = emptySet()
                        }
                    },
                items = exerciseGroups,
                selection = selectedExerciseGroups,
                onSelectionChange = { newSelection -> selectedExerciseGroups = newSelection} ,
                itemContent = { it ->
                    ExpandableCard(
                        isExpandable = it.exercises.isNotEmpty(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (it.enabled) 1f else 0.4f)
                            .combinedClickable(
                                onClick = {
                                    if (selectionMode) {
                                        val newSelection =
                                            if (selectedExerciseGroups.contains(it)) {
                                                selectedExerciseGroups - it
                                            } else {
                                                selectedExerciseGroups + it
                                            }
                                        selectedExerciseGroups = newSelection
                                    } else {
                                        val exerciseGroupId = exerciseGroups.indexOf(it)
                                        navController.navigate(
                                            Screen.getRoute(
                                                Screen.ExerciseGroupDetail,
                                                workoutId,
                                                exerciseGroupId
                                            )
                                        )
                                    }
                                },
                                onLongClick = { if (!selectionMode) selectionMode = true }
                            ),
                        title = { modifier -> ExerciseGroupTitle(modifier,it) },
                        content = { ExerciseGroupContent(it) }
                    )
                }
            )
        }
    }
}