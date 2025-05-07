package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MoveDown
import androidx.compose.material3.AlertDialog
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
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.collectAsState
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
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.MoveExercisesToWorkoutDialog
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.getEnabledStatusOfWorkoutComponent
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.cloneWorkoutComponent
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.ui.theme.DarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumLightGray
import com.gabstra.myworkoutassistant.ui.theme.LightGray
import com.gabstra.myworkoutassistant.ui.theme.MediumDarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumGray
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

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
    workout: Workout,
    workoutComponent: WorkoutComponent,
    showRest: Boolean,
    appViewModel: AppViewModel
) {
    when (workoutComponent) {
        is Exercise -> {
            ExerciseRenderer(
                exercise = workoutComponent,
                showRest = showRest,
                appViewModel = appViewModel
            )
        }

        is Rest ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                StyledCard(modifier = Modifier.wrapContentSize()) {
                    Row(
                        modifier = Modifier.padding(15.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "Rest for: " + formatTime(workoutComponent.timeInSeconds),
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = if (workoutComponent.enabled) .87f else .3f),
                            textAlign = TextAlign.Center
                        )
                    }
                }
            }

        is Superset -> {
            val superSet = workoutComponent as Superset

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .border(1.dp, MediumGray),
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Row(
                    modifier = Modifier.padding(15.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 10.dp)
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = "Super Set",
                        style = MaterialTheme.typography.bodyLarge,
                        color =  if (superSet.enabled) LightGray else MediumDarkGray,
                    )
                }
                Column(
                    modifier = Modifier.padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    superSet.exercises.forEach { exercise ->
                        ExerciseRenderer(
                            modifier = Modifier.clickable {
                                appViewModel.setScreenData(
                                    ScreenData.ExerciseDetail(
                                        workout.id,
                                        exercise.id
                                    )
                                )
                            },
                            exercise = exercise,
                            showRest = showRest,
                            appViewModel = appViewModel
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun SupersetForm(
    displayDialog: MutableState<Boolean>,
    appViewModel: AppViewModel,
    workout: Workout,
) {
    var selectedWorkoutComponents by remember { mutableStateOf(listOf<WorkoutComponent>()) }

    val hms = remember { mutableStateOf(TimeConverter.secondsToHms(0)) }
    val (hours, minutes, seconds) = hms.value

    if (displayDialog.value) {
        val scrollState = rememberScrollState()

        AlertDialog(
            onDismissRequest = { displayDialog.value = false },
            title = { Text("Add Superset", color = LightGray) },
            text = {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(top = 10.dp)
                        .verticalColumnScrollbar(scrollState)
                        .verticalScroll(scrollState),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {

                    Text("Rest Time Between Sets", color = LightGray)
                    CustomTimePicker(
                        initialHour = hours,
                        initialMinute = minutes,
                        initialSecond = seconds,
                        onTimeChange = { hour, minute, second ->
                            hms.value = Triple(hour, minute, second)
                        }
                    )


                    val validItems =
                        remember { workout.workoutComponents.filter { it is Exercise && it.enabled } }

                    Spacer(modifier = Modifier.height(10.dp))
                    Text("Select at least two exercises", color = LightGray)
                    validItems.forEach { item ->
                        val exercise = item as Exercise

                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE)
                                .clickable {
                                    if (selectedWorkoutComponents.any { it === item }) {
                                        selectedWorkoutComponents =
                                            selectedWorkoutComponents.filter { it !== item }
                                    } else {
                                        selectedWorkoutComponents = selectedWorkoutComponents + item
                                    }
                                },
                            text = exercise.name,
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(
                                alpha = if (selectedWorkoutComponents.contains(
                                        exercise
                                    )
                                ) .87f else .3f
                            ),
                        )
                    }

                    Text("Selected exercises:")
                    selectedWorkoutComponents.forEach { it ->
                        Text((it as Exercise).name)
                    }
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val newSuperset = Superset(
                            id = UUID.randomUUID(),
                            exercises = selectedWorkoutComponents.map { it as Exercise },
                            timeInSeconds = TimeConverter.hmsTotalSeconds(hours, minutes, seconds),
                            enabled = true
                        )

                        val newWorkoutComponents = workout.workoutComponents.filter { item ->
                            selectedWorkoutComponents.none { it === item }
                        } + newSuperset

                        val adjustedComponents =
                            ensureRestSeparatedByExercises(newWorkoutComponents)
                        val updatedWorkout = workout.copy(workoutComponents = adjustedComponents)
                        appViewModel.updateWorkoutOld(workout, updatedWorkout)
                        displayDialog.value = false
                    },
                    enabled = selectedWorkoutComponents.size >= 2
                ) {
                    Text("Create Super set")
                }
            },
            dismissButton = {
                TextButton(onClick = { displayDialog.value = false }) {
                    Text("Cancel")
                }
            }
        )
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutDetailScreen(
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    setHistoryDao: SetHistoryDao,
    exerciseInfoDao: ExerciseInfoDao,
    workout: Workout,
    onGoBack: () -> Unit
) {
    var selectedWorkoutComponents by remember { mutableStateOf(listOf<WorkoutComponent>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    var displaySupersetDialog = remember { mutableStateOf(false) }

    var showRest by remember { mutableStateOf(false) }

    var showMoveWorkoutDialog by remember { mutableStateOf(false) }
    val allWorkouts by appViewModel.workoutsFlow.collectAsState()

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
                        enabled = (selectedWorkoutComponents.size == 1 && workout.workoutComponents.indexOfFirst { it === selectedWorkoutComponents.first() } != 0),
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

                            val adjustedComponents =
                                ensureRestSeparatedByExercises(newWorkoutComponents)
                            val updatedWorkout =
                                workout.copy(workoutComponents = adjustedComponents)
                            appViewModel.updateWorkoutOld(workout, updatedWorkout)
                        }) {
                        Icon(
                            imageVector = Icons.Filled.ArrowUpward,
                            contentDescription = "Go Higher",
                            tint = Color.White.copy(alpha = .87f)
                        )
                    }
                    IconButton(
                        enabled = (selectedWorkoutComponents.size == 1 && workout.workoutComponents.indexOfFirst { it === selectedWorkoutComponents.first() } != workout.workoutComponents.size - 1),
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

                            val adjustedComponents =
                                ensureRestSeparatedByExercises(newWorkoutComponents)
                            val updatedWorkout =
                                workout.copy(workoutComponents = adjustedComponents)
                            appViewModel.updateWorkoutOld(workout, updatedWorkout)
                        }) {
                        Icon(
                            imageVector = Icons.Filled.ArrowDownward,
                            contentDescription = "Go Lower", tint = Color.White.copy(alpha = .87f)
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

                                val adjustedComponents =
                                    ensureRestSeparatedByExercises(updatedWorkoutComponents)

                                val updatedWorkout =
                                    workout.copy(workoutComponents = adjustedComponents)
                                appViewModel.updateWorkoutOld(workout, updatedWorkout)

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

                                val adjustedComponents =
                                    ensureRestSeparatedByExercises(updatedWorkoutComponents)

                                val updatedWorkout =
                                    workout.copy(workoutComponents = adjustedComponents)
                                appViewModel.updateWorkoutOld(workout, updatedWorkout)
                                selectedWorkoutComponents = emptyList()
                                isSelectionModeActive = false
                            }) {
                            Text("Disable")
                        }
                    }

                    IconButton(
                        enabled = selectedWorkoutComponents.isNotEmpty(),
                        onClick = {
                            val newWorkoutComponents = selectedWorkoutComponents.map {
                                cloneWorkoutComponent(it)
                            }

                            val updatedWorkout =
                                workout.copy(workoutComponents = workout.workoutComponents + newWorkoutComponents)
                            appViewModel.updateWorkoutOld(workout, updatedWorkout)
                            selectedWorkoutComponents = emptyList()

                        }) {
                        val isEnabled = selectedWorkoutComponents.isNotEmpty()
                        val color =
                            if (isEnabled) Color.White.copy(alpha = .87f) else Color.White.copy(
                                alpha = .3f
                            )

                        Icon(
                            imageVector = Icons.Default.ContentCopy,
                            contentDescription = "Copy",
                            tint = color
                        )
                    }
                    IconButton(
                        enabled = selectedWorkoutComponents.isNotEmpty(),
                        onClick = { showMoveWorkoutDialog = true }
                    ) {
                        Icon(
                            imageVector = Icons.Default.MoveDown,
                            contentDescription = "Move to Another Workout",
                            tint = Color.White.copy(alpha = .87f)
                        )
                    }
                    IconButton(onClick = {
                        val superSetExercises =
                            selectedWorkoutComponents.filterIsInstance<Superset>()
                                .flatMap { it.exercises }

                        val newWorkoutComponents = workout.workoutComponents.filter { item ->
                            selectedWorkoutComponents.none { it === item }
                        } + superSetExercises

                        val adjustedComponents =
                            ensureRestSeparatedByExercises(newWorkoutComponents)

                        val updatedWorkout = workout.copy(workoutComponents = adjustedComponents)
                        appViewModel.updateWorkoutOld(workout, updatedWorkout)
                        selectedWorkoutComponents = emptyList()
                        isSelectionModeActive = false

                        val selectedExerciseIds =
                            selectedWorkoutComponents.toList().filterIsInstance<Exercise>()
                                .map { it.id }
                        if (selectedExerciseIds.isNotEmpty()) {
                            scope.launch {
                                withContext(Dispatchers.IO) {
                                    selectedExerciseIds.forEach {
                                        setHistoryDao.deleteByExerciseId(it)
                                        exerciseInfoDao.deleteById(it)
                                    }
                                }
                            }
                        }
                    }) {
                        Icon(
                            imageVector = Icons.Default.Delete,
                            contentDescription = "Delete",
                            tint = Color.White.copy(alpha = .87f)
                        )
                    }
                }
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = DarkGray, titleContentColor = LightGray),
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
                                    workoutRecordDao.deleteByWorkoutId(workout.id)
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
        },
        bottomBar = {
            if (selectedWorkoutComponents.isNotEmpty()) {
                StyledCard {
                    editModeBottomBar()
                }
            }
        },
    ) { it ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .background(DarkGray)
                    .padding(it),
                verticalArrangement = Arrangement.Center,
            ) {
                TabRow(
                    contentColor = DarkGray,
                    selectedTabIndex = 0,
                    indicator = { tabPositions ->
                        TabRowDefaults.Indicator(
                            Modifier.tabIndicatorOffset(tabPositions[0]),
                            color = MaterialTheme.colorScheme.primary,
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    Tab(
                        modifier = Modifier.background(DarkGray),
                        selected = true,
                        onClick = { },
                        text = {
                            Text(
                                text = "Overview"
                            )
                        },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MediumLightGray,
                        interactionSource = object : MutableInteractionSource {
                            override val interactions: Flow<Interaction> = emptyFlow()

                            override suspend fun emit(interaction: Interaction) {
                                // Empty implementation
                            }

                            override fun tryEmit(interaction: Interaction): Boolean = true
                        }
                    )
                    Tab(
                        modifier = Modifier.background(DarkGray),
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
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MediumLightGray,
                        interactionSource = object : MutableInteractionSource {
                            override val interactions: Flow<Interaction> = emptyFlow()

                            override suspend fun emit(interaction: Interaction) {
                                // Empty implementation
                            }

                            override fun tryEmit(interaction: Interaction): Boolean = true
                        }
                    )
                }

                val scrollState = rememberScrollState()

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(top = 10.dp)
                        .verticalColumnScrollbar(scrollState)
                        .verticalScroll(scrollState)
                        .padding(horizontal = 15.dp),
                ) {
                    if (workout.workoutComponents.isEmpty()) {
                        StyledCard(
                            modifier = Modifier
                                .padding(15.dp),
                            
                        ) {
                            Text(
                                text = "Add a new workout component",
                                textAlign = TextAlign.Center,
                                color = Color.White.copy(alpha = .87f),
                                modifier = Modifier
                                    .padding(15.dp)
                            )
                        }
                    }else{
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.End,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 20.dp)
                        ) {
                            Row(
                                modifier = Modifier.padding(vertical = 15.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(10.dp)
                            ) {
                                Checkbox(
                                    modifier = Modifier.size(10.dp),
                                    checked = showRest,
                                    onCheckedChange = { showRest = it },
                                    colors = CheckboxDefaults.colors().copy(
                                        checkedCheckmarkColor = MaterialTheme.colorScheme.background
                                    )
                                )
                                Text(text = "Show Rests", style = MaterialTheme.typography.bodySmall)
                            }
                        }

                        GenericSelectableList(
                            it = null,
                            items = if (!showRest) workout.workoutComponents.filter { it !is Rest } else workout.workoutComponents,
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

                                    else -> {}
                                }
                            },
                            onEnableSelection = { isSelectionModeActive = true },
                            onDisableSelection = { isSelectionModeActive = false },
                            onSelectionChange = { newSelection ->
                                selectedWorkoutComponents = newSelection
                            },
                            onOrderChange = { newWorkoutComponents ->
                                if (!showRest) return@GenericSelectableList

                                val adjustedComponents =
                                    ensureRestSeparatedByExercises(newWorkoutComponents)
                                val updatedWorkout =
                                    workout.copy(workoutComponents = adjustedComponents)
                                appViewModel.updateWorkoutOld(workout, updatedWorkout)
                            },
                            itemContent = { it ->
                                WorkoutComponentRenderer(
                                    workout = workout,
                                    workoutComponent = it,
                                    showRest = showRest,
                                    appViewModel = appViewModel
                                )
                            },
                            isDragDisabled = true
                        )
                    }

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
                                },
                                MenuItem("Add Superset") {
                                    displaySupersetDialog.value = true
                                }
                            ),
                            content = {
                                Icon(
                                    imageVector = Icons.Filled.Add,
                                    contentDescription = "Add",
                                    tint = LightGray,
                                )
                            }
                        )
                    }
                }

                SupersetForm(displaySupersetDialog, appViewModel, workout)

                MoveExercisesToWorkoutDialog(
                    show = showMoveWorkoutDialog,
                    onDismiss = { showMoveWorkoutDialog = false },
                    workouts = allWorkouts,
                    currentWorkout = workout,
                    onMove = { targetWorkout ->
                        appViewModel.moveComponents(workout, selectedWorkoutComponents, targetWorkout)

                        selectedWorkoutComponents = emptyList()
                        isSelectionModeActive = false
                        Toast.makeText(
                            context,
                            "Selection moved to ${targetWorkout.name}",
                            Toast.LENGTH_SHORT
                        ).show()

                        appViewModel.setScreenData(ScreenData.WorkoutDetail(targetWorkout.id))
                    }
                )
            }

    }
}

fun ensureRestSeparatedByExercises(components: List<WorkoutComponent>): List<WorkoutComponent> {
    val adjustedComponents = mutableListOf<WorkoutComponent>()
    var lastWasExercise = false

    for (component in components) {
        if (component !is Rest) {
            adjustedComponents.add(component)
            lastWasExercise = true
        } else {
            if (lastWasExercise) {
                //check if the next component if exist is exercise and enabled
                val nextComponentIndex = components.indexOf(component) + 1
                if (nextComponentIndex < components.size) {
                    val nextComponent = components[nextComponentIndex]
                    if (nextComponent.enabled) {
                        adjustedComponents.add(component)
                    } else {
                        adjustedComponents.add(component.copy(enabled = false))
                    }
                }
            }

            lastWasExercise = false
        }
    }
    return adjustedComponents
}