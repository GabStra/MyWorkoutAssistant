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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.DarkModeContainer
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.getEnabledStatusOfWorkoutComponent
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.cloneWorkoutComponent
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
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
            modifier = Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh)
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
fun WorkoutComponentRenderer(
    workoutComponent: WorkoutComponent,
    showRest:Boolean
) {
    when (workoutComponent) {
        is Exercise -> ExerciseRenderer(
            exercise = workoutComponent,
            showRest = showRest
        )

        is Rest ->
            DarkModeContainer(whiteOverlayAlpha = .1f) {
                Row(
                    modifier = Modifier.padding(15.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        modifier = Modifier.weight(1f),
                        text = "Rest for: "+ formatTime(workoutComponent.timeInSeconds),
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = if (workoutComponent.enabled) .87f else .3f),
                        textAlign = TextAlign.Center
                    )
                }
            }

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

    var showRest by remember { mutableStateOf(true) }

    var isDragDisabled by remember {
        mutableStateOf(false)
    }

    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(showRest) {
        selectedWorkoutComponents = emptyList()
    }

    val editModeBottomBar = @Composable {
        BottomAppBar(
            contentPadding = PaddingValues(0.dp),
            containerColor = Color.Transparent,
            actions = {
                Row(
                    modifier = Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(
                        enabled = showRest && (selectedWorkoutComponents.size == 1 && workout.workoutComponents.indexOfFirst { it === selectedWorkoutComponents.first() } != 0),
                        onClick = {
                            val currentWorkoutComponents = workout.workoutComponents
                            val selectedComponent = selectedWorkoutComponents.first()

                            val selectedIndex =
                                currentWorkoutComponents.indexOfFirst { it === selectedComponent }

                            val newWorkoutComponents =
                                currentWorkoutComponents.toMutableList().apply {
                                    removeAt(selectedIndex)
                                    add(selectedIndex - 1, selectedComponent)
                                }

                            val adjustedComponents = ensureRestSeparatedByExercises(newWorkoutComponents)
                            val updatedWorkout = workout.copy(workoutComponents = adjustedComponents)
                            appViewModel.updateWorkoutOld(workout, updatedWorkout)
                        }) {
                        Icon(
                            imageVector = Icons.Filled.ArrowUpward,
                            contentDescription = "Go Higher",
                            tint = Color.White.copy(alpha = .87f)
                        )
                    }
                    IconButton(
                        enabled = showRest && (selectedWorkoutComponents.size == 1 && workout.workoutComponents.indexOfFirst { it === selectedWorkoutComponents.first() } != workout.workoutComponents.size - 1),
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

                            val adjustedComponents = ensureRestSeparatedByExercises(newWorkoutComponents)
                            val updatedWorkout = workout.copy(workoutComponents = adjustedComponents)
                            appViewModel.updateWorkoutOld(workout, updatedWorkout)
                        }) {
                        Icon(
                            imageVector = Icons.Filled.ArrowDownward,
                            contentDescription = "Go Lower"
                            ,tint = Color.White.copy(alpha = .87f)
                        )
                    }
                    if (selectedWorkoutComponents.any { !getEnabledStatusOfWorkoutComponent(it) }) {
                        Button(
                            modifier = Modifier.padding(5.dp),
                            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                            onClick = {
                                val updatedWorkoutComponents =
                                    workout.workoutComponents.map { workoutComponent ->
                                        if (selectedWorkoutComponents.any { it === workoutComponent }) {
                                            when (workoutComponent) {
                                                is Exercise -> workoutComponent.copy(enabled = true)
                                                is Rest -> workoutComponent.copy(enabled = true)
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
                    } else {
                        Button(
                            modifier = Modifier.padding(5.dp),
                            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                            onClick = {
                                val updatedWorkoutComponents =
                                    workout.workoutComponents.map { workoutComponent ->
                                        if (selectedWorkoutComponents.any { it === workoutComponent }) {
                                            when (workoutComponent) {
                                                is Exercise -> workoutComponent.copy(enabled = false)
                                                is Rest -> workoutComponent.copy(enabled = false)
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

                    IconButton(
                        enabled = selectedWorkoutComponents.size == 1,
                        onClick = {
                            val newWorkoutComponent =
                                cloneWorkoutComponent(selectedWorkoutComponents.first())

                            appViewModel.addWorkoutComponent(workout, newWorkoutComponent)
                            selectedWorkoutComponents = emptyList()
                            isSelectionModeActive = false
                        }) {
                        val isEnabled = selectedWorkoutComponents.size == 1
                        val color = if (isEnabled) Color.White.copy(alpha = .87f) else Color.White.copy(
                            alpha = .3f
                        )

                        Icon(imageVector = Icons.Default.ContentCopy, contentDescription = "Copy",tint = color)
                    }
                    IconButton(onClick = {
                        val newWorkoutComponents = workout.workoutComponents.filter { item ->
                            selectedWorkoutComponents.none { it === item }
                        }

                        val updatedWorkout = workout.copy(workoutComponents = newWorkoutComponents)
                        appViewModel.updateWorkout(workout, updatedWorkout)
                        selectedWorkoutComponents = emptyList()
                        isSelectionModeActive = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete",tint = Color.White.copy(alpha = .87f))
                    }
                }
            }
        )
    }

    Scaffold(
        topBar = {
            DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(),
                            textAlign = TextAlign.Center,
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
                                        Toast.makeText(
                                            context,
                                            "History deleted",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            }
                        )
                    }
                )
            }
        },
        bottomBar = {
            DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
                if (selectedWorkoutComponents.isNotEmpty()) {
                    editModeBottomBar()
                } else {
                    BottomAppBar(
                        contentPadding = PaddingValues(0.dp),
                        containerColor = Color.Transparent,
                        actions = {
                            Row(
                                modifier = Modifier
                                    .fillMaxSize(),
                                horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                                verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                            ) {
                                GenericButtonWithMenu(
                                    menuItems = listOf(
                                        MenuItem("Add Exercise") {
                                            appViewModel.setScreenData(
                                                ScreenData.NewExercise(
                                                    workout.id
                                                )
                                            );
                                        },
                                        MenuItem("Add Rests Between Exercises") {
                                            appViewModel.setScreenData(
                                                ScreenData.NewRest(
                                                    workout.id,
                                                    null
                                                )
                                            );
                                        }

                                    ),
                                    content = {  Text("New Exercise") }
                                )
                            }
                        }
                    )

                }
            }
        },
    ) { it ->
        if (workout.workoutComponents.isEmpty()) {
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
                        color = Color.White.copy(alpha = .87f),
                        modifier = Modifier
                            .padding(15.dp)
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
                            color = MaterialTheme.colorScheme.primary,
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
                        Tab(
                            selected = true,
                            onClick = { },
                            text = {
                                Text(
                                    text = "Overview"
                                )
                            },
                            selectedContentColor = Color.White.copy(alpha = .87f),
                            unselectedContentColor = Color.White.copy(alpha = .3f),
                        )
                    }
                    DarkModeContainer(whiteOverlayAlpha = .05f, isRounded = false) {
                        Tab(
                            selected = false,
                            onClick = {
                                appViewModel.setScreenData(
                                    ScreenData.WorkoutHistory(workout.id),
                                    true
                                )
                            },
                            text = {
                                Text(

                                    text = "History"
                                )
                            },
                            selectedContentColor = Color.White.copy(alpha = .87f),
                            unselectedContentColor = Color.White.copy(alpha = .3f),
                        )
                    }
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.End,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 20.dp)
                ) {
                    Checkbox(
                        checked = showRest,
                        onCheckedChange = { showRest = it },
                        colors =  CheckboxDefaults.colors().copy(
                            checkedCheckmarkColor =  MaterialTheme.colorScheme.background
                        )
                    )
                    Text(text = "Show Rests")
                }

                GenericSelectableList(
                    it = PaddingValues(0.dp, 5.dp),
                    items = if(!showRest) workout.workoutComponents.filter { it !is Rest } else workout.workoutComponents,
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

                            is Rest -> {
                                appViewModel.setScreenData(
                                    ScreenData.EditRest(
                                        workout.id,
                                        it
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
                        if(!showRest) return@GenericSelectableList

                        val adjustedComponents = ensureRestSeparatedByExercises(newWorkoutComponents)
                        val updatedWorkout = workout.copy(workoutComponents = adjustedComponents)
                        appViewModel.updateWorkoutOld(workout, updatedWorkout)
                    },
                    itemContent = { it ->
                        WorkoutComponentRenderer(
                            workoutComponent = it,
                            showRest = showRest
                        )
                    },
                    isDragDisabled = true
                )
            }
        }
    }
}

fun ensureRestSeparatedByExercises(components: List<WorkoutComponent>): List<WorkoutComponent> {
    val adjustedComponents = mutableListOf<WorkoutComponent>()
    var lastWasExercise = false

    for (component in components) {
        if(component !is Rest) {
            adjustedComponents.add(component)
            lastWasExercise = true
        }else{
            if(lastWasExercise){
                adjustedComponents.add(component)
            }

            lastWasExercise = false
        }
    }
    return adjustedComponents
}