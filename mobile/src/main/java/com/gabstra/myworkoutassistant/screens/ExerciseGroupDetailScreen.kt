package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
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
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.DarkModeContainer
import com.gabstra.myworkoutassistant.composables.ExerciseGroupRenderer
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.getEnabledStatusOfWorkoutComponent
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent


@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseGroupDetailScreen(
    appViewModel: AppViewModel,
    workout: Workout,
    exerciseGroup: ExerciseGroup,
    onGoBack: () -> Unit
) {
    var workoutComponents by remember(exerciseGroup) { mutableStateOf(exerciseGroup.workoutComponents) }

    var selectedWorkoutComponents by remember { mutableStateOf(listOf<WorkoutComponent>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    var isDragDisabled by remember {
        mutableStateOf(false)
    }

    Scaffold(
        topBar = {
            DarkModeContainer(whiteOverlayAlpha =.2f, isRounded = false) {
                TopAppBar(
                    title = {
                        Text(
                            modifier = Modifier.fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            textAlign = TextAlign.Center,
                            text = exerciseGroup.name
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
                                ScreenData.EditExerciseGroup(
                                    workout.id,
                                    exerciseGroup.id
                                )
                            );
                        }) {
                            Icon(imageVector = Icons.Default.Settings, contentDescription = "Back")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surfaceContainerHigh
                    )
                )
            }
        },
        bottomBar = {
            if (selectedWorkoutComponents.isNotEmpty()) {
                BottomAppBar(
                    containerColor = Color.DarkGray,
                    actions = {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceEvenly,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            IconButton(
                                enabled = selectedWorkoutComponents.size == 1 && workoutComponents.indexOfFirst { it === selectedWorkoutComponents.first() } != 0,
                                onClick = {
                                    val currentWorkoutComponents = workoutComponents
                                    val selectedComponent = selectedWorkoutComponents.first()

                                    val selectedIndex =
                                        currentWorkoutComponents.indexOfFirst { it === selectedComponent }

                                    val newWorkoutComponents =
                                        currentWorkoutComponents.toMutableList().apply {
                                            removeAt(selectedIndex)
                                            add(selectedIndex - 1, selectedComponent)
                                        }

                                    val updatedExerciseGroup = exerciseGroup.copy(
                                        workoutComponents = newWorkoutComponents
                                    )
                                    appViewModel.updateWorkoutComponent(
                                        workout,
                                        exerciseGroup,
                                        updatedExerciseGroup
                                    )
                                    workoutComponents = newWorkoutComponents
                                }) {
                                Icon(
                                    imageVector = Icons.Filled.ArrowUpward,
                                    contentDescription = "Go Higher"
                                )
                            }
                            IconButton(
                                enabled = selectedWorkoutComponents.size == 1 && workout.workoutComponents.indexOfFirst { it === selectedWorkoutComponents.first() } != workoutComponents.size - 1,
                                onClick = {
                                    val currentWorkoutComponents = workout.workoutComponents
                                    val selectedComponent = selectedWorkoutComponents.first()

                                    val selectedIndex =
                                        currentWorkoutComponents.indexOfFirst { it === selectedComponent }

                                    val newWorkoutComponents =
                                        currentWorkoutComponents.toMutableList().apply {
                                            removeAt(selectedIndex)
                                            add(selectedIndex + 1, selectedComponent)
                                        }

                                    val updatedExerciseGroup = exerciseGroup.copy(
                                        workoutComponents = newWorkoutComponents
                                    )
                                    appViewModel.updateWorkoutComponent(
                                        workout,
                                        exerciseGroup,
                                        updatedExerciseGroup
                                    )
                                    workoutComponents = newWorkoutComponents
                                }) {
                                Icon(
                                    imageVector = Icons.Filled.ArrowDownward,
                                    contentDescription = "Go Lower"
                                )
                            }

                            if (selectedWorkoutComponents.any {
                                    !getEnabledStatusOfWorkoutComponent(
                                        it
                                    )
                                }) {
                                Button(
                                    modifier = Modifier.padding(5.dp),
                                    onClick = {
                                        for (workoutComponent in selectedWorkoutComponents) {
                                            val updatedWorkoutComponent = when (workoutComponent) {
                                                is Exercise -> workoutComponent.copy(enabled = true)
                                                is ExerciseGroup -> workoutComponent.copy(enabled = true)
                                            }

                                            appViewModel.updateWorkoutComponent(
                                                workout,
                                                workoutComponent,
                                                updatedWorkoutComponent
                                            )
                                        }
                                        selectedWorkoutComponents = emptyList()
                                        isSelectionModeActive = false
                                    }) {
                                    Text("Enable")
                                }
                            } else {
                                Button(
                                    modifier = Modifier.padding(5.dp),
                                    onClick = {
                                        for (workoutComponent in selectedWorkoutComponents) {
                                            val updatedWorkoutComponent = when (workoutComponent) {
                                                is Exercise -> workoutComponent.copy(enabled = false)
                                                is ExerciseGroup -> workoutComponent.copy(enabled = false)
                                            }
                                            appViewModel.updateWorkoutComponent(
                                                workout,
                                                workoutComponent,
                                                updatedWorkoutComponent
                                            )
                                        }
                                        selectedWorkoutComponents = emptyList()
                                        isSelectionModeActive = false
                                    }) {
                                    Text("Disable")
                                }
                            }

                            IconButton(
                                enabled = selectedWorkoutComponents.size == 1,
                                onClick = {
                                    val selectedWorkoutComponent = selectedWorkoutComponents.first()
                                    val newWorkoutComponent = when (selectedWorkoutComponent) {
                                        is Exercise -> selectedWorkoutComponent.copy(id = java.util.UUID.randomUUID())
                                        is ExerciseGroup -> selectedWorkoutComponent.copy(id = java.util.UUID.randomUUID())
                                    }
                                    appViewModel.addWorkoutComponentToExerciseGroup(
                                        workout,
                                        exerciseGroup,
                                        newWorkoutComponent
                                    )
                                    workoutComponents = workoutComponents + newWorkoutComponent
                                    selectedWorkoutComponents = emptyList()
                                    isSelectionModeActive = false
                                }) {
                                Icon(
                                    imageVector = Icons.Default.ContentCopy,
                                    contentDescription = "Copy"
                                )
                            }
                            IconButton(onClick = {
                                val updatedExerciseGroup = exerciseGroup.copy(
                                    workoutComponents = workoutComponents.filter { component ->
                                        selectedWorkoutComponents.none { it === component }
                                    }
                                )
                                workoutComponents = updatedExerciseGroup.workoutComponents
                                appViewModel.updateWorkoutComponent(
                                    workout,
                                    exerciseGroup,
                                    updatedExerciseGroup
                                )
                                selectedWorkoutComponents = emptyList()
                                isSelectionModeActive = false
                            }) {
                                Icon(
                                    imageVector = Icons.Default.Delete,
                                    contentDescription = "Delete"
                                )
                            }
                        }
                    }
                )
            }else{
                BottomAppBar(
                    containerColor = Color.DarkGray,
                    actions = {
                        GenericButtonWithMenu(
                            menuItems = listOf(
                                MenuItem("Add Exercise") {
                                    appViewModel.setScreenData(
                                        ScreenData.NewExercise(
                                            workout.id,
                                            exerciseGroup.id
                                        )
                                    )
                                },
                                MenuItem("Add Exercise Group") {
                                    appViewModel.setScreenData(
                                        ScreenData.NewExerciseGroup(
                                            workout.id,
                                            exerciseGroup.id
                                        )
                                    )
                                }

                            ),
                            content = { Icon(Icons.Filled.Add, contentDescription = "Add") }
                        )
                    }
                )
            }
        },
    ) { it ->


        if (workoutComponents.isEmpty()) {
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
                        text = "Add a new workout component",
                        textAlign = TextAlign.Center,
                        color = Color.White,
                        modifier = Modifier
                            .padding(15.dp)
                    )
                }
            }
        } else {
            GenericSelectableList(
                it,
                items = workoutComponents,
                selectedItems = selectedWorkoutComponents,
                isSelectionModeActive,
                onItemClick = {
                    when (it) {
                        is Exercise -> {
                            appViewModel.setScreenData(ScreenData.ExerciseDetail(workout.id, it.id))
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
                onSelectionChange = { newSelection -> selectedWorkoutComponents = newSelection },
                onOrderChange = { newWorkoutComponents ->
                    val updatedExerciseGroup = exerciseGroup.copy(
                        workoutComponents = newWorkoutComponents
                    )
                    appViewModel.updateWorkoutComponent(
                        workout,
                        exerciseGroup,
                        updatedExerciseGroup
                    )
                    workoutComponents = newWorkoutComponents
                },
                itemContent = { it ->
                    ExpandableContainer(
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
                            when (it) {
                                is Exercise -> ExerciseRenderer(it)
                                is ExerciseGroup -> ExerciseGroupRenderer(it)
                            }
                        },
                        onOpen = { isDragDisabled = true },
                        onClose = { isDragDisabled = false }
                    )
                },
                isDragDisabled = true
            )
        }
    }
}