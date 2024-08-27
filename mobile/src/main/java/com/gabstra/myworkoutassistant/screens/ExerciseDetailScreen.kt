package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.DarkModeContainer
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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
                        text = "Reps: ${set.reps}",
                        color = Color.White.copy(alpha = .87f),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        modifier = Modifier.weight(1f),
                        text = "Weight: ${set.weight}kg",
                        color = Color.White.copy(alpha = .87f),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            is BodyWeightSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "Reps: ${set.reps}",
                    color = Color.White.copy(alpha = .87f),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }

            is EnduranceSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${formatSecondsToMinutesSeconds(set.timeInMillis / 1000)} (mm:ss)",
                    textAlign = TextAlign.Center,
                    color = Color.White.copy(alpha = .87f),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }

            is TimedDurationSet -> {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${formatSecondsToMinutesSeconds(set.timeInMillis / 1000)} (mm:ss)",
                    textAlign = TextAlign.Center,
                    color = Color.White.copy(alpha = .87f),
                    style = MaterialTheme.typography.bodyMedium,
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
    var sets by remember { mutableStateOf(exercise.sets) }
    var selectedSets by remember { mutableStateOf(listOf<com.gabstra.myworkoutassistant.shared.sets.Set>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            DarkModeContainer(whiteOverlayAlpha =.1f, isRounded = false) {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            textAlign = TextAlign.Center,
                            text = exercise.name
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
                        IconButton(onClick = {
                            appViewModel.setScreenData(
                                ScreenData.EditExercise(
                                    workout.id,
                                    exercise.id
                                )
                            );
                        }) {
                            Icon(
                                imageVector = Icons.Default.Settings,
                                contentDescription = "Settings"
                            )
                        }
                    }
                )
            }
        },
        bottomBar = {
            DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false){
            if (selectedSets.isNotEmpty()) {
                BottomAppBar(
                    contentPadding = PaddingValues(0.dp),
                    containerColor = Color.Transparent,
                    actions = {
                        Row(
                            modifier = Modifier
                                .background(MaterialTheme.colorScheme.background)
                                .fillMaxSize(),
                            horizontalArrangement = Arrangement.SpaceEvenly,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            IconButton(onClick = {
                                val newSets = sets.filter { set ->
                                    selectedSets.none { it === set }
                                }
                                sets = newSets
                                val updatedExercise = exercise.copy(sets = newSets)

                                appViewModel.updateWorkoutComponent(
                                    workout,
                                    exercise,
                                    updatedExercise
                                )
                                selectedSets = emptyList()
                                isSelectionModeActive = false
                            }) {
                                Icon(
                                    imageVector = Icons.Default.Delete,
                                    contentDescription = "Delete"
                                )
                            }
                            IconButton(
                                enabled = selectedSets.size == 1,
                                onClick = {
                                    val selectedSet = selectedSets.first()
                                    val newSet = when (selectedSet) {
                                        is WeightSet -> selectedSet.copy(id = java.util.UUID.randomUUID())
                                        is BodyWeightSet -> selectedSet.copy(id = java.util.UUID.randomUUID())
                                        is EnduranceSet -> selectedSet.copy(id = java.util.UUID.randomUUID())
                                        is TimedDurationSet -> selectedSet.copy(id = java.util.UUID.randomUUID())
                                    }
                                    appViewModel.addSetToExercise(workout, exercise, newSet)

                                    sets = sets + newSet
                                    selectedSets = emptyList()
                                    isSelectionModeActive = false
                                }) {
                                Icon(
                                    imageVector = Icons.Default.ContentCopy,
                                    contentDescription = "Copy"
                                )
                            }
                        }
                    }
                )
            }else{
                BottomAppBar(
                    contentPadding = PaddingValues(0.dp),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxSize(),
                        horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                        verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                    ){
                        Button(
                            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                            onClick = {
                                appViewModel.setScreenData(
                                    ScreenData.NewSet(workout.id, exercise.id)
                                )
                            },
                        ) {
                            Text("Add")
                        }
                    }
                }
            }
            }
        },
    ) { it ->
        if (sets.isEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                DarkModeContainer(
                    modifier = Modifier
                        .padding(15.dp),
                    whiteOverlayAlpha = .1f
                ) {
                    Text(
                        text = "Add a new set",
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .padding(15.dp),
                        color = Color.White.copy(alpha = .87f),
                    )
                }
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it),
                verticalArrangement = Arrangement.Center,
            ) {
                TabRow(
                    selectedTabIndex = 0,
                    indicator = { tabPositions ->
                        TabRowDefaults.Indicator(
                            Modifier.tabIndicatorOffset(tabPositions[0]),
                            color = MaterialTheme.colorScheme.primary, // Set the indicator color
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    DarkModeContainer(whiteOverlayAlpha =.1f, isRounded = false) {
                        Tab(
                            selected = true,
                            onClick = { },
                            text = { Text(text = "Overview") },
                            selectedContentColor = Color.White.copy(alpha = .87f),
                            unselectedContentColor = Color.White.copy(alpha = .3f),
                        )
                    }
                    DarkModeContainer(whiteOverlayAlpha =.05f, isRounded = false) {
                        Tab(
                            selected = false,
                            onClick = {
                                appViewModel.setScreenData(
                                    ScreenData.ExerciseHistory(workout.id, exercise.id),
                                    true
                                )
                            },
                            text = { Text(text = "History") },
                            selectedContentColor = Color.White.copy(alpha = .87f),
                            unselectedContentColor = Color.White.copy(alpha = .3f),
                        )
                    }
                }

                GenericSelectableList(
                    it = PaddingValues(0.dp, 5.dp),
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
                    isDragDisabled = true,
                    itemContent = { it ->
                        DarkModeContainer(whiteOverlayAlpha = .1f) {
                            SetRenderer(it)
                        }
                    }
                )
            }
        }
    }
}