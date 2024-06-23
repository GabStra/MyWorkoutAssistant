package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
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
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.cloneWorkoutComponent
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun Menu(
    onEditWorkout: () -> Unit,
    onClearHistory: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier.wrapContentSize(Alignment.TopEnd)
    ) {
        IconButton(onClick = { expanded = !expanded }) {
            Icon(
                imageVector = Icons.Default.MoreVert,
                contentDescription = "More"
            )
        }

        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier.background(Color.Black)
        ) {
            DropdownMenuItem(
                text = { Text("Edit Workout") },
                onClick = {
                    onEditWorkout()
                    expanded = false
                }
            )
            DropdownMenuItem(
                text = { Text("Clear History") },
                onClick = {
                    onClearHistory()
                    expanded = false
                }
            )
        }
    }
}


@Composable
fun WorkoutComponentTitle(modifier: Modifier, workoutComponent: WorkoutComponent) {
    Row(
        horizontalArrangement = Arrangement.End,
        modifier = modifier.padding(15.dp),
    ) {
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
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workout: Workout,
    onGoBack: () -> Unit
) {
    var selectedWorkoutComponents by remember { mutableStateOf(listOf<WorkoutComponent>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    var isDragDisabled by remember {
        mutableStateOf(false)
    }

    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val editModeBottomBar = @Composable {
        BottomAppBar(
            actions = {
                IconButton(onClick = {
                    val newWorkoutComponents = workout.workoutComponents.filter { item ->
                        selectedWorkoutComponents.none { it === item }
                    }

                    val updatedWorkout = workout.copy(workoutComponents = newWorkoutComponents)
                    appViewModel.updateWorkout(workout, updatedWorkout)
                    selectedWorkoutComponents = emptyList()
                    isSelectionModeActive = false
                }) {
                    Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                }
                IconButton(
                    enabled = selectedWorkoutComponents.size == 1,
                    onClick = {
                        val newWorkoutComponent = cloneWorkoutComponent(selectedWorkoutComponents.first())

                        appViewModel.addWorkoutComponent(workout, newWorkoutComponent)
                        selectedWorkoutComponents = emptyList()
                        isSelectionModeActive = false
                    }) {
                    Icon(imageVector = Icons.Default.ContentCopy, contentDescription = "Copy")
                }
                Button(
                    modifier = Modifier.padding(5.dp),
                    onClick = {
                        val updatedWorkoutComponents =
                            workout.workoutComponents.map { workoutComponent ->
                                if (selectedWorkoutComponents.any { it === workoutComponent }) {
                                    when (workoutComponent) {
                                        is Exercise -> workoutComponent.copy(enabled = true)
                                        is ExerciseGroup -> workoutComponent.copy(enabled = true)
                                        else -> workoutComponent
                                    }
                                } else {
                                    workoutComponent
                                }
                            }

                        val updatedWorkout =
                            workout.copy(workoutComponents = updatedWorkoutComponents)
                        appViewModel.updateWorkout(workout, updatedWorkout)

                        selectedWorkoutComponents = emptyList()
                        isSelectionModeActive = false
                    }) {
                    Text("Enable")
                }
                Button(
                    modifier = Modifier.padding(5.dp),
                    onClick = {
                        val updatedWorkoutComponents =
                            workout.workoutComponents.map { workoutComponent ->
                                if (selectedWorkoutComponents.any { it === workoutComponent }) {
                                    when (workoutComponent) {
                                        is Exercise -> workoutComponent.copy(enabled = false)
                                        is ExerciseGroup -> workoutComponent.copy(enabled = false)
                                        else -> workoutComponent
                                    }
                                } else {
                                    workoutComponent
                                }
                            }

                        val updatedWorkout =
                            workout.copy(workoutComponents = updatedWorkoutComponents)
                        appViewModel.updateWorkout(workout, updatedWorkout)
                        selectedWorkoutComponents = emptyList()
                        isSelectionModeActive = false
                    }) {
                    Text("Disable")
                }
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        modifier = Modifier.basicMarquee(),
                        text = workout.name
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
                    Menu(
                        onEditWorkout = {
                            appViewModel.setScreenData(ScreenData.EditWorkout(workout.id));
                        },
                        onClearHistory = {
                            scope.launch {
                                withContext(Dispatchers.Main) {
                                    workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                                    Toast.makeText(context, "History deleted", Toast.LENGTH_SHORT).show()
                                }
                            }
                        }
                    )
                }
            )
        },
        bottomBar = {
            if (selectedWorkoutComponents.isNotEmpty()) editModeBottomBar()
        },
        floatingActionButton = {
            if (selectedWorkoutComponents.isEmpty())
                GenericFloatingActionButtonWithMenu(
                    menuItems = listOf(
                        MenuItem("Add Exercise") {
                            appViewModel.setScreenData(ScreenData.NewExercise(workout.id, null));
                        },
                        MenuItem("Add Exercise Group") {
                            appViewModel.setScreenData(
                                ScreenData.NewExerciseGroup(
                                    workout.id,
                                    null
                                )
                            );
                        }

                    ),
                    fabIcon = { Icon(Icons.Filled.Add, contentDescription = "Add") }
                )
        },
    ) { it ->
        if (workout.workoutComponents.isEmpty()) {
            Text(
                modifier = Modifier
                    .padding(it)
                    .fillMaxSize(),
                text = "Add a new workout component",
                textAlign = TextAlign.Center
            )
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
                            color = Color.White, // Set the indicator color
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    Tab(
                        selected = true,
                        onClick = { },
                        text = { Text("Overview") },
                        selectedContentColor = Color.White, // Color when tab is selected
                        unselectedContentColor = Color.LightGray // Color when tab is not selected
                    )
                    Tab(
                        selected = false,
                        onClick = {
                            appViewModel.setScreenData(
                                ScreenData.WorkoutHistory(workout.id),
                                true
                            )
                        },
                        text = { Text("History") },
                        selectedContentColor = Color.White, // Color when tab is selected
                        unselectedContentColor = Color.LightGray // Color when tab is not selected
                    )
                }

                GenericSelectableList(
                    it = PaddingValues(0.dp, 5.dp),
                    items = workout.workoutComponents,
                    selectedItems = selectedWorkoutComponents,
                    isSelectionModeActive,
                    onItemClick = {
                        when (it) {
                            is Exercise -> {
                                appViewModel.setScreenData(
                                    ScreenData.ExerciseDetail(
                                        workout.id,
                                        it.id
                                    )
                                )
                            }

                            is ExerciseGroup -> {
                                appViewModel.setScreenData(
                                    ScreenData.ExerciseGroupDetail(
                                        workout.id,
                                        it.id
                                    )
                                )
                            }
                        }
                    },
                    onEnableSelection = { isSelectionModeActive = true },
                    onDisableSelection = { isSelectionModeActive = false },
                    onSelectionChange = { newSelection ->
                        selectedWorkoutComponents = newSelection
                    },
                    onOrderChange = { newWorkoutComponents ->
                        val updatedWorkout = workout.copy(workoutComponents = newWorkoutComponents)
                        appViewModel.updateWorkout(workout, updatedWorkout)
                    },
                    itemContent = { it ->
                        ExpandableCard(
                            isExpandable = when (it) {
                                is Exercise -> it.sets.isNotEmpty()
                                is ExerciseGroup -> it.workoutComponents.isNotEmpty()
                                else -> false
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .alpha(if (it.enabled) 1f else 0.4f),
                            title = { modifier -> WorkoutComponentTitle(modifier, it) },
                            content = {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 10.dp, vertical = 5.dp)
                                        .clip(RoundedCornerShape(5.dp))
                                        .background(Color.Black),
                                    horizontalAlignment = Alignment.CenterHorizontally
                                ) {
                                    when (it) {
                                        is Exercise -> ExerciseRenderer(it)
                                        is ExerciseGroup -> ExerciseGroupRenderer(it)
                                    }
                                }
                            },
                            onOpen = { isDragDisabled = true },
                            onClose = { isDragDisabled = false }
                        )
                    },
                    isDragDisabled = false
                )
            }
        }
    }
}