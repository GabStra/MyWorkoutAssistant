package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup

@Composable
fun SetRenderer(set: Set) {
    Row(
        modifier = Modifier.padding(15.dp),
        horizontalArrangement = Arrangement.Center
    ) {
        when (set) {
            is WeightSet -> {
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
                    text = "Reps: ${set.reps}",
                )
            }

            is EnduranceSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${formatSecondsToMinutesSeconds(set.timeInMillis/1000)} (mm:ss)",
                    textAlign = TextAlign.Center,
                )
            }

            is TimedDurationSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${formatSecondsToMinutesSeconds(set.timeInMillis/1000)} (mm:ss)",
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseDetailScreen(
    appViewModel: AppViewModel,
    workout: Workout,
    setHistoryDao: SetHistoryDao,
    exercise: Exercise,
    onGoBack: () -> Unit
) {
    var sets  by remember { mutableStateOf(exercise.sets) }
    var selectedSets by remember { mutableStateOf(listOf<com.gabstra.myworkoutassistant.shared.sets.Set>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        modifier = Modifier.basicMarquee(),
                        text=exercise.name
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                }
            )
        },
        bottomBar = {
            if (selectedSets.isNotEmpty()) BottomAppBar(
                actions = {
                    IconButton(onClick = {
                        val newSets = sets.filter { set ->
                            selectedSets.none { it === set }
                        }
                        sets = newSets
                        val updatedExercise = exercise.copy(sets = newSets)

                        appViewModel.updateWorkoutComponent(workout, exercise, updatedExercise)
                        selectedSets = emptyList()
                        isSelectionModeActive = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                    IconButton(
                        enabled = selectedSets.size == 1,
                        onClick = {
                            val selectedSet = selectedSets.first()
                            val newSet = when (selectedSet) {
                                is WeightSet -> selectedSet.copy(id= java.util.UUID.randomUUID())
                                is BodyWeightSet -> selectedSet.copy(id= java.util.UUID.randomUUID())
                                is EnduranceSet -> selectedSet.copy(id= java.util.UUID.randomUUID())
                                is TimedDurationSet -> selectedSet.copy(id= java.util.UUID.randomUUID())
                            }
                            appViewModel.addSetToExercise(workout, exercise, newSet)
                            
                            sets = sets + newSet
                            selectedSets = emptyList()
                            isSelectionModeActive = false
                        }) {
                        Icon(imageVector = Icons.Default.ContentCopy, contentDescription = "Copy")
                    }
                }
            )
        },
        floatingActionButton = {
            if (selectedSets.isEmpty()) {
                FloatingActionButton(
                    onClick = {
                        appViewModel.setScreenData(ScreenData.NewSet(workout.id, exercise.id));
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
        if (sets.isEmpty()) {
            Text(
                modifier = Modifier
                    .padding(it)
                    .fillMaxSize(), text = "Add a new set", textAlign = TextAlign.Center
            )
        } else {
            GenericSelectableList(
                it,
                items = sets,
                selectedItems = selectedSets,
                isSelectionModeActive,
                onItemClick = { },
                onEnableSelection = { isSelectionModeActive = true },
                onDisableSelection = { isSelectionModeActive = false },
                onSelectionChange = { newSelection -> selectedSets = newSelection },
                onOrderChange = { newSets ->
                    val updatedExercise = exercise.copy(sets = newSets)
                    appViewModel.updateWorkoutComponent(workout, exercise, updatedExercise)
                    sets = newSets
                },
                itemContent = { it ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        SetRenderer(it)
                    }
                }
            )
        }
    }
}